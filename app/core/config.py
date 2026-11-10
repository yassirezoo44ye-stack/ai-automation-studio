"""
Axon Automation Studio — central configuration.

Every environment variable the platform reads is declared once, on
``AxonSettings``, and validated at import time. A missing or unsafe value
stops the process with a clear ``FATAL:`` line instead of letting it boot in a
half-configured state. Secret values are held as ``SecretStr`` so they never
show up in ``repr()``, logs or tracebacks.

The module-level constants below the settings class (``DATABASE_URL``,
``SESSION_SECRET``, ``WORKSPACES``, ...) are kept for the existing call sites
that import them directly.

Token encryption
----------------
``TokenCipher`` encrypts third-party credentials (OAuth access/refresh tokens,
provider API keys, webhook signing secrets) with AES-256-GCM before they are
written to the database. Each ciphertext is bound to its tenant and purpose
through the GCM associated data, so a ciphertext copied into another tenant's
row, or reused for another purpose, fails to decrypt. Keys are versioned:

    AXON_TOKEN_ENCRYPTION_KEYS="k2026b:<base64url 32 bytes>,k2026a:<base64url 32 bytes>"

The first key encrypts; every listed key can decrypt, so rotation is: put a
new key first, re-encrypt rows with ``TokenCipher.rotate()``, then drop the old
key. Generate a key with::

    python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
"""
from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os
import re
import sys
import uuid
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import stripe as _stripe
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

log = logging.getLogger(__name__)

PRODUCT_NAME = "Axon Automation Studio"
PRODUCT_SHORT_NAME = "Axon"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Values that must never protect a production deployment. Compared
# case-insensitively against the whole secret and as substrings.
_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "change-me", "changeme", "replace-me", "not-for-production", "your-secret",
    "secret-here", "insecure", "example",
)
_WEAK_SECRETS: frozenset[str] = frozenset({"secret", "password", "dev", "test", "axon"})

MIN_SECRET_LENGTH = 32
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PG_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_VALID_ENVIRONMENTS = ("development", "test", "staging", "production")


class ConfigurationError(RuntimeError):
    """The environment is missing a value, or holds an unsafe one."""


class TokenDecryptionError(Exception):
    """A ciphertext could not be decrypted (tampered, wrong tenant/purpose, or unknown key).

    Deliberately carries no detail about which check failed.
    """


def _split_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _is_placeholder(secret: str) -> bool:
    lowered = secret.strip().lower()
    if lowered in _WEAK_SECRETS:
        return True
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    # One repeated character ("aaaa...") carries no entropy whatever its length.
    return len(set(lowered)) < 4


_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _decode_key(material: str) -> bytes:
    if not _B64URL_RE.match(material):
        raise ValueError("key material is not valid base64url")
    padded = material + "=" * (-len(material) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("key material is not valid base64url") from exc
    if len(raw) != 32:
        raise ValueError(f"key must decode to exactly 32 bytes, got {len(raw)}")
    if len(set(raw)) < 8:
        raise ValueError("key material has too little entropy")
    return raw


def parse_key_ring(spec: str) -> tuple[str, dict[str, bytes]]:
    """Parse ``"kid:key,kid2:key2"`` into (primary key id, {key id: key bytes})."""
    ring: dict[str, bytes] = {}
    primary: str | None = None
    entries = _split_csv(spec)
    if not entries:
        raise ValueError("no keys configured")
    for entry in entries:
        kid, sep, material = entry.partition(":")
        kid, material = kid.strip(), material.strip()
        if not sep or not kid or not material:
            raise ValueError("each key must be written as <key-id>:<base64url key>")
        if not _KEY_ID_RE.match(kid):
            raise ValueError(f"invalid key id {kid!r} (letters, digits, '_' or '-', max 32)")
        if kid in ring:
            raise ValueError(f"duplicate key id {kid!r}")
        try:
            ring[kid] = _decode_key(material)
        except ValueError as exc:
            raise ValueError(f"key {kid!r}: {exc}") from None
        primary = primary or kid
    if len(set(ring.values())) != len(ring):
        raise ValueError("two key ids share the same key material")
    assert primary is not None
    return primary, ring


class TokenCipher:
    """AES-256-GCM envelope for secrets at rest.

    Envelope: ``axv1.<key id>.<base64url(nonce || ciphertext || tag)>``.
    Associated data: ``axon/v1|<purpose>|<tenant id>`` — never stored, always
    recomputed by the caller, so it binds the ciphertext to where it lives.
    """

    VERSION = "axv1"
    NONCE_BYTES = 12
    MAX_PLAINTEXT_BYTES = 64 * 1024
    _PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")

    __slots__ = ("_aeads", "_primary")

    def __init__(self, keys: Mapping[str, bytes], primary_key_id: str) -> None:
        if primary_key_id not in keys:
            raise ConfigurationError("primary key id is not in the key ring")
        self._primary = primary_key_id
        self._aeads = {kid: AESGCM(key) for kid, key in keys.items()}

    @classmethod
    def from_spec(cls, spec: str) -> TokenCipher:
        primary, ring = parse_key_ring(spec)
        return cls(ring, primary)

    def __repr__(self) -> str:
        return f"TokenCipher(primary={self._primary!r}, keys={sorted(self._aeads)!r})"

    @property
    def primary_key_id(self) -> str:
        return self._primary

    @property
    def key_ids(self) -> frozenset[str]:
        return frozenset(self._aeads)

    @classmethod
    def _aad(cls, tenant_id: uuid.UUID | str, purpose: str) -> bytes:
        if not cls._PURPOSE_RE.match(purpose):
            raise ValueError(f"invalid purpose {purpose!r}")
        tenant = uuid.UUID(str(tenant_id))  # normalises case and rejects garbage
        return f"axon/v1|{purpose}|{tenant}".encode()

    def encrypt(self, plaintext: str, *, tenant_id: uuid.UUID | str, purpose: str) -> str:
        if not isinstance(plaintext, str):
            raise TypeError("plaintext must be str")
        data = plaintext.encode("utf-8")
        if len(data) > self.MAX_PLAINTEXT_BYTES:
            raise ValueError("plaintext too large")
        nonce = os.urandom(self.NONCE_BYTES)
        sealed = self._aeads[self._primary].encrypt(nonce, data, self._aad(tenant_id, purpose))
        payload = base64.urlsafe_b64encode(nonce + sealed).rstrip(b"=").decode("ascii")
        return f"{self.VERSION}.{self._primary}.{payload}"

    @classmethod
    def key_id_of(cls, token: str) -> str:
        parts = token.split(".") if isinstance(token, str) else []
        if len(parts) != 3 or parts[0] != cls.VERSION or not _KEY_ID_RE.match(parts[1]):
            raise TokenDecryptionError("malformed ciphertext")
        return parts[1]

    def decrypt(self, token: str, *, tenant_id: uuid.UUID | str, purpose: str) -> str:
        aad = self._aad(tenant_id, purpose)
        kid = self.key_id_of(token)
        aead = self._aeads.get(kid)
        if aead is None:
            raise TokenDecryptionError("unknown key id")
        payload = token.split(".", 2)[2]
        if not _B64URL_RE.match(payload):
            raise TokenDecryptionError("malformed ciphertext")
        try:
            blob = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        except (binascii.Error, ValueError):
            raise TokenDecryptionError("malformed ciphertext") from None
        if len(blob) < self.NONCE_BYTES + 16:
            raise TokenDecryptionError("malformed ciphertext")
        nonce, sealed = blob[: self.NONCE_BYTES], blob[self.NONCE_BYTES :]
        try:
            return aead.decrypt(nonce, sealed, aad).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError):
            raise TokenDecryptionError("decryption failed") from None

    def needs_rotation(self, token: str) -> bool:
        return self.key_id_of(token) != self._primary

    def rotate(self, token: str, *, tenant_id: uuid.UUID | str, purpose: str) -> str:
        """Re-encrypt under the primary key (no-op when already current)."""
        if not self.needs_rotation(token):
            return token
        plaintext = self.decrypt(token, tenant_id=tenant_id, purpose=purpose)
        return self.encrypt(plaintext, tenant_id=tenant_id, purpose=purpose)


_SSLMODE_TO_ASYNCPG: dict[str, Any] = {
    "disable": False,
    "allow": "allow",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}


def build_async_url(raw_url: str) -> tuple[URL, dict[str, Any]]:
    """Turn a libpq-style DATABASE_URL into an asyncpg SQLAlchemy URL + connect args.

    ``sslmode`` is a libpq option asyncpg does not accept as a query parameter,
    so it is moved into ``connect_args["ssl"]``.
    """
    url = make_url(raw_url)
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("only PostgreSQL is supported")
    query = dict(url.query)
    connect_args: dict[str, Any] = {}
    sslmode = query.pop("sslmode", None) or query.pop("ssl", None)
    if sslmode is not None:
        mode = str(sslmode if isinstance(sslmode, str) else sslmode[0]).lower()
        if mode not in _SSLMODE_TO_ASYNCPG:
            raise ValueError(f"unsupported sslmode {mode!r}")
        connect_args["ssl"] = _SSLMODE_TO_ASYNCPG[mode]
    return url.set(drivername="postgresql+asyncpg", query=query), connect_args


def _env(name: str, *aliases: str) -> Any:
    return Field(validation_alias=AliasChoices(name, *aliases))


class AxonSettings(BaseSettings):
    """Every environment variable Axon reads, validated in one place."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
        frozen=True,
    )

    environment: str = Field("production", validation_alias=AliasChoices("ENVIRONMENT", "AXON_ENV"))

    # ── Secrets ──────────────────────────────────────────────────────────────
    database_url: SecretStr = _env("DATABASE_URL")
    session_secret: SecretStr = _env("SESSION_SECRET")
    token_encryption_keys: SecretStr | None = Field(
        None, validation_alias=AliasChoices("AXON_TOKEN_ENCRYPTION_KEYS", "TOKEN_ENCRYPTION_KEYS"),
    )

    # ── Database pool (SQLAlchemy engine in app/core/db.py) ──────────────────
    db_pool_size: int = Field(
        10, ge=1, le=200, validation_alias=AliasChoices("DB_POOL_SIZE", "AXON_DB_POOL_SIZE"),
    )
    db_max_overflow: int = Field(
        10, ge=0, le=200, validation_alias=AliasChoices("DB_MAX_OVERFLOW", "AXON_DB_MAX_OVERFLOW"),
    )
    db_pool_timeout_s: float = Field(
        10.0, gt=0, le=120, validation_alias=AliasChoices("AXON_DB_POOL_TIMEOUT_S", "DB_ACQUIRE_TIMEOUT_S"),
    )
    db_pool_recycle_s: int = Field(1800, ge=60, le=86400, validation_alias=AliasChoices("AXON_DB_POOL_RECYCLE_S"))
    db_statement_timeout_ms: int = Field(
        30000, ge=0, le=3_600_000, validation_alias=AliasChoices("AXON_DB_STATEMENT_TIMEOUT_MS"),
    )
    db_rls_role: str = Field("axon_app", validation_alias=AliasChoices("AXON_DB_RLS_ROLE"))
    db_echo: bool = Field(False, validation_alias=AliasChoices("DB_ECHO", "AXON_DB_ECHO"))

    # ── Authentication (app/core/axon_auth.py) ───────────────────────────────
    auth_access_ttl_s: int = Field(
        600, ge=60, le=3600, validation_alias=AliasChoices("AXON_AUTH_ACCESS_TTL_S"),
    )
    auth_refresh_ttl_s: int = Field(
        14 * 86400, ge=3600, le=90 * 86400, validation_alias=AliasChoices("AXON_AUTH_REFRESH_TTL_S"),
    )
    auth_session_max_age_s: int = Field(
        30 * 86400, ge=3600, le=365 * 86400, validation_alias=AliasChoices("AXON_AUTH_SESSION_MAX_AGE_S"),
    )
    auth_jwt_issuer: str = Field("axon", validation_alias=AliasChoices("AXON_AUTH_JWT_ISSUER"))
    auth_jwt_audience: str = Field("axon-api", validation_alias=AliasChoices("AXON_AUTH_JWT_AUDIENCE"))
    auth_allow_signup: bool = Field(True, validation_alias=AliasChoices("AXON_AUTH_ALLOW_SIGNUP"))

    # ── URLs / CORS ──────────────────────────────────────────────────────────
    app_url: str = Field("http://localhost:8000", validation_alias=AliasChoices("APP_URL"))
    frontend_url: str | None = Field(None, validation_alias=AliasChoices("FRONTEND_URL"))
    extra_cors_origins: str = Field("", validation_alias=AliasChoices("EXTRA_CORS_ORIGINS"))

    # ── Stripe ───────────────────────────────────────────────────────────────
    stripe_secret_key: SecretStr = Field(SecretStr(""), validation_alias=AliasChoices("STRIPE_SECRET_KEY"))
    stripe_webhook_secret: SecretStr = Field(SecretStr(""), validation_alias=AliasChoices("STRIPE_WEBHOOK_SECRET"))
    stripe_price_id: str = Field("", validation_alias=AliasChoices("STRIPE_PRICE_ID"))
    stripe_price_id_starter: str = Field("", validation_alias=AliasChoices("STRIPE_PRICE_ID_STARTER"))
    stripe_price_id_pro: str = Field("", validation_alias=AliasChoices("STRIPE_PRICE_ID_PRO"))
    stripe_price_id_team: str = Field("", validation_alias=AliasChoices("STRIPE_PRICE_ID_TEAM"))

    # ── Filesystem / access ──────────────────────────────────────────────────
    workspaces_dir: Path = Field(_PROJECT_ROOT / "workspaces", validation_alias=AliasChoices("WORKSPACES_DIR"))
    admin_emails: str = Field("", validation_alias=AliasChoices("ADMIN_EMAILS"))

    # ── Career assistant (read-only mailbox consent) ─────────────────────────
    career_google_client_id: str = Field("", validation_alias=AliasChoices("CAREER_GOOGLE_CLIENT_ID"))
    career_google_client_secret: SecretStr = Field(
        SecretStr(""), validation_alias=AliasChoices("CAREER_GOOGLE_CLIENT_SECRET"),
    )
    career_google_redirect_uri: str = Field("", validation_alias=AliasChoices("CAREER_GOOGLE_REDIRECT_URI"))

    # ── Field validators ─────────────────────────────────────────────────────
    @field_validator("environment", mode="before")
    @classmethod
    def _normalise_environment(cls, value: Any) -> str:
        env = str(value or "production").strip().lower()
        # Unknown values fail closed to production rules.
        return env if env in _VALID_ENVIRONMENTS else "production"

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value().strip()
        scheme = url.split("://", 1)[0].lower() if "://" in url else ""
        if scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError("DATABASE_URL must be a PostgreSQL URL (postgresql://user:pass@host:port/db)")
        return SecretStr(url)

    @field_validator("db_rls_role")
    @classmethod
    def _check_role(cls, value: str) -> str:
        value = value.strip()
        if value and not _PG_IDENTIFIER_RE.match(value):
            raise ValueError("AXON_DB_RLS_ROLE must be a lowercase PostgreSQL identifier")
        return value

    @field_validator("app_url", "frontend_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not re.match(r"^https?://[^\s/]+", value):
            raise ValueError("must be an absolute http(s) URL")
        return value

    @field_validator("token_encryption_keys")
    @classmethod
    def _check_key_ring(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            parse_key_ring(value.get_secret_value())
        except ValueError as exc:
            raise ValueError(f"AXON_TOKEN_ENCRYPTION_KEYS is invalid: {exc}") from None
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> AxonSettings:
        secret = self.session_secret.get_secret_value()
        if not secret.strip():
            raise ValueError("SESSION_SECRET is empty")
        if self.is_production_like:
            if len(secret) < MIN_SECRET_LENGTH:
                raise ValueError(
                    f"SESSION_SECRET must be at least {MIN_SECRET_LENGTH} characters outside development",
                )
            if _is_placeholder(secret):
                raise ValueError("SESSION_SECRET is a placeholder value; generate a real secret")
        if self.token_encryption_keys is not None:
            _, ring = parse_key_ring(self.token_encryption_keys.get_secret_value())
            secret_bytes = secret.encode()
            if any(hmac.compare_digest(key, secret_bytes[:32]) for key in ring.values()):
                raise ValueError("token encryption keys must not reuse SESSION_SECRET")
        if self.auth_refresh_ttl_s > self.auth_session_max_age_s:
            raise ValueError("AXON_AUTH_REFRESH_TTL_S cannot exceed AXON_AUTH_SESSION_MAX_AGE_S")
        if self.auth_access_ttl_s >= self.auth_refresh_ttl_s:
            raise ValueError("AXON_AUTH_ACCESS_TTL_S must be shorter than AXON_AUTH_REFRESH_TTL_S")
        if self.environment == "production" and not self.db_rls_role:
            raise ValueError("AXON_DB_RLS_ROLE cannot be empty in production")
        return self

    # ── Derived values ───────────────────────────────────────────────────────
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """DATABASE_URL rewritten for SQLAlchemy + asyncpg (``postgresql+asyncpg://``, no ``sslmode``)."""
        return build_async_url(self.database_url.get_secret_value())[0].render_as_string(hide_password=False)

    @property
    def DB_ECHO(self) -> bool:
        return self.db_echo

    @property
    def DB_POOL_SIZE(self) -> int:
        return self.db_pool_size

    @property
    def DB_MAX_OVERFLOW(self) -> int:
        return self.db_max_overflow

    @property
    def is_production_like(self) -> bool:
        return self.environment in {"production", "staging"}

    @property
    def effective_frontend_url(self) -> str:
        return self.frontend_url or self.app_url

    @property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.extra_cors_origins)

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(e.lower() for e in _split_csv(self.admin_emails))

    def token_cipher(self) -> TokenCipher:
        """Build the cipher, or raise when no keys are configured (never a throwaway key)."""
        if self.token_encryption_keys is None:
            raise ConfigurationError(
                "AXON_TOKEN_ENCRYPTION_KEYS is not set; integration tokens cannot be stored or read",
            )
        return TokenCipher.from_spec(self.token_encryption_keys.get_secret_value())


def _describe_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        field = str(loc[0]).upper() if loc else "configuration"
        msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
        if err.get("type") == "missing":
            msg = "is not set"
        lines.append(f"{field} {msg}" if err.get("type") == "missing" else f"{field}: {msg}")
    return "; ".join(lines)


def load_settings(**overrides: Any) -> AxonSettings:
    """Read and validate the environment. Raises ConfigurationError with a readable message."""
    try:
        return AxonSettings(**overrides)
    except ValidationError as exc:
        raise ConfigurationError(_describe_errors(exc)) from None


try:
    settings: AxonSettings = load_settings()
except ConfigurationError as _exc:
    _hint = ""
    if "SESSION_SECRET" in str(_exc):
        _hint = (
            " Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            " and set it in your environment."
        )
    print(f"FATAL: {_exc}.{_hint}", file=sys.stderr)
    sys.exit(1)


@lru_cache(maxsize=1)
def get_token_cipher() -> TokenCipher:
    """Process-wide cipher built from ``settings``. Raises ConfigurationError if unconfigured."""
    return settings.token_cipher()


if settings.token_encryption_keys is None and settings.is_production_like:
    log.warning(
        "AXON_TOKEN_ENCRYPTION_KEYS is not set: storing or reading integration credentials will fail",
    )

# ── Legacy module-level constants (existing imports depend on these) ─────────
DATABASE_URL: str = settings.database_url.get_secret_value()
SESSION_SECRET: str = settings.session_secret.get_secret_value()

TOKEN_TTL: int = 60 * 20  # 20 minutes — sub_token is re-minted on every /refresh
# call (see refresh_token() in app/routers/auth_users.py) alongside the access
# token, so a short TTL costs nothing in practice but bounds how long a
# captured sub_token stays valid after logout/expiry. See
# docs/SUB_TOKEN_P0_DECISION.md.

_stripe.api_key = settings.stripe_secret_key.get_secret_value()
STRIPE_WEBHOOK_SECRET: str = settings.stripe_webhook_secret.get_secret_value()
STRIPE_PRICE_ID: str = settings.stripe_price_id  # legacy flat $/mo trial gate
APP_URL: str = settings.app_url
# Where the browser-facing frontend lives (e.g. a Vercel deployment).
FRONTEND_URL: str = settings.effective_frontend_url
# Additional CORS origins for a split frontend/backend deployment.
EXTRA_CORS_ORIGINS: list[str] = settings.cors_origins

# Org-scoped tiered plans (Enterprise is contact-sales — no Stripe price).
STRIPE_PRICE_ID_STARTER: str = settings.stripe_price_id_starter
STRIPE_PRICE_ID_PRO: str = settings.stripe_price_id_pro
STRIPE_PRICE_ID_TEAM: str = settings.stripe_price_id_team

# ── Filesystem ────────────────────────────────────────────────────────────────
WORKSPACES: Path = settings.workspaces_dir
DIST_DIR: Path = _PROJECT_ROOT / "dist_packages"

# ── Seeded single-tenant identities (legacy public schema) ───────────────────
USER_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
DEMO_PROJECT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ── Public API prefixes (no auth token required) ──────────────────────────────
PUBLIC_PREFIXES: tuple = (
    "/api/auth/",
    "/api/subscription/",
    "/api/stripe/",
    "/api/health/",
    "/health",
    "/api/track",             # anonymous attribution — no auth, rate-limited inside the handler
    "/api/discover",          # public creation feed — endpoint-level auth still guards /mine
    "/api/business/stream/",  # SSE plan stream — ticket-validated inside the handler
    "/api/webhooks/auto/",    # automation webhooks — HMAC-verified inside the handler
    "/api/axon/",             # Axon core — every route authenticates itself (app/core/axon_auth.py)
)

# ── Platform admins ───────────────────────────────────────────────────────────
# Allowlist of emails permitted to hold the "admin" API-key scope. Empty by
# default: an unconfigured deployment grants nobody "admin".
ADMIN_EMAILS: frozenset[str] = settings.admin_email_set


# ── Environment ───────────────────────────────────────────────────────────────
# Read live (not cached at import time) so tests can toggle ENVIRONMENT
# without reloading this module. Unknown/unset values are treated as
# "production" so a missing or misspelled value never relaxes a deployment.
def get_environment() -> str:
    return os.getenv("ENVIRONMENT", "production").strip().lower()


def is_development() -> bool:
    return get_environment() == "development"


# Career assistant: separate read-only mailbox consent from Google sign-in.
CAREER_GOOGLE_CLIENT_ID: str = settings.career_google_client_id
CAREER_GOOGLE_CLIENT_SECRET: str = settings.career_google_client_secret.get_secret_value()
CAREER_GOOGLE_REDIRECT_URI: str = settings.career_google_redirect_uri
