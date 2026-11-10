"""
Axon security primitives — no database, no FastAPI.

Everything here is a pure function or a small value object, so it can be
unit-tested exhaustively and reused by the HTTP layer (app/core/axon_auth.py),
background workers and the webhook receiver.

* Key derivation      every purpose gets its own HKDF-SHA256 subkey of
                      SESSION_SECRET, so a leak of one digest/signature key
                      tells an attacker nothing about the others.
* Passwords           Argon2id (argon2-cffi); verifies the legacy bcrypt
                      hashes of app/core/passwords.py and asks for a rehash.
                      Unknown e-mails are verified against a dummy hash so
                      response time does not reveal whether an account exists.
* Access tokens       short-lived JWT (HS256 only, issuer/audience/type/kid
                      pinned, every claim required).
* Refresh tokens      opaque random strings; only an HMAC digest is stored.
* API keys            ``axk_<12 id chars>_<43 secret chars>``; the id part is
                      the lookup prefix, the database keeps an HMAC digest of
                      the whole key.
* Webhook signatures  ``t=<unix>,v1=<hex>`` over ``"<t>.<delivery id>." + body``,
                      several v1 values allowed during secret rotation,
                      timestamp tolerance enforced.

Legacy modules (app/core/auth.py, security.py, jwt_utils.py, passwords.py)
keep serving the existing public-schema routers unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import bcrypt
import jwt
from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import Type as _Argon2Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import AxonSettings, settings

__all__ = [
    "AccessClaims",
    "ApiKeyFormatError",
    "GeneratedApiKey",
    "PasswordPolicyError",
    "TokenError",
    "WebhookVerificationError",
    "decode_access_token",
    "derive_key",
    "generate_api_key",
    "generate_webhook_secret",
    "hash_api_key",
    "hash_api_key_hex",
    "hash_password",
    "hash_refresh_token",
    "issue_access_token",
    "new_refresh_token",
    "parse_api_key",
    "password_needs_rehash",
    "sign_webhook",
    "validate_password",
    "verify_password",
    "verify_webhook_signature",
]


# ═════════════════════════════════════════════════════════════════════════════
# Key derivation
# ═════════════════════════════════════════════════════════════════════════════

_KDF_SALT = b"axon/kdf/v1"

# Every derived key is named here so two features can never share one by accident.
PURPOSE_ACCESS_TOKEN = "axon/jwt/access/v1"
PURPOSE_REFRESH_TOKEN = "axon/refresh-token/v1"
PURPOSE_API_KEY = "axon/api-key/v1"


@lru_cache(maxsize=32)
def _derive(secret: bytes, purpose: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, info=purpose.encode()).derive(secret)


def derive_key(purpose: str, cfg: AxonSettings | None = None) -> bytes:
    """32-byte subkey of SESSION_SECRET dedicated to ``purpose``."""
    if not purpose or not purpose.startswith("axon/"):
        raise ValueError("key purposes must be namespaced under 'axon/'")
    secret = (cfg or settings).session_secret.get_secret_value().encode("utf-8")
    return _derive(secret, purpose)


def _hmac256(key: bytes, data: str | bytes) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hmac.new(key, data, hashlib.sha256).digest()


# ═════════════════════════════════════════════════════════════════════════════
# Passwords
# ═════════════════════════════════════════════════════════════════════════════

PASSWORD_MIN_LENGTH = 12
# Bounds the hashing work an anonymous request can trigger.
PASSWORD_MAX_LENGTH = 256

# OWASP-recommended Argon2id parameters (m=19 MiB, t=2, p=1) rounded up.
_argon2 = _Argon2Hasher(time_cost=3, memory_cost=19 * 1024, parallelism=1, hash_len=32,
                        salt_len=16, type=_Argon2Type.ID)

# Verified when the e-mail is unknown or has no password, so the timing of a
# failed login does not depend on whether the account exists.
_DUMMY_HASH = _argon2.hash(secrets.token_urlsafe(24))

_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "passw0rd", "123456789012", "1234567890",
    "qwertyuiop", "qwerty123456", "iloveyou", "letmein", "welcome", "welcome123",
    "admin", "admin123", "administrator", "changeme", "monkey", "dragon", "football",
    "baseball", "sunshine", "princess", "trustno1", "abc123456789", "111111111111",
    "000000000000", "aaaaaaaaaaaa", "p@ssw0rd", "p@ssword123", "superman", "starwars",
})


class PasswordPolicyError(ValueError):
    """The password does not meet the policy; ``reasons`` lists every failure."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _normalise_password(password: str) -> str:
    # NFKC so the same password typed on different keyboards/IMEs (Arabic
    # presentation forms, full-width digits) hashes identically.
    return unicodedata.normalize("NFKC", password)


def validate_password(password: str, *, email: str | None = None) -> None:
    """Raise PasswordPolicyError unless ``password`` is acceptable."""
    if not isinstance(password, str):
        raise PasswordPolicyError(["password must be a string"])
    pw = _normalise_password(password)
    reasons: list[str] = []
    if len(pw) < PASSWORD_MIN_LENGTH:
        reasons.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(pw) > PASSWORD_MAX_LENGTH:
        reasons.append(f"must be at most {PASSWORD_MAX_LENGTH} characters")
    if pw != pw.strip():
        reasons.append("must not start or end with whitespace")
    if any(unicodedata.category(c) == "Cc" for c in pw):
        reasons.append("must not contain control characters")
    if len(set(pw)) < 4:
        reasons.append("must use at least 4 different characters")
    lowered = pw.casefold()
    if lowered in _COMMON_PASSWORDS:
        reasons.append("is too common")
    if email:
        local = email.split("@", 1)[0].casefold()
        if len(local) >= 3 and local in lowered:
            reasons.append("must not contain your e-mail name")
    if reasons:
        raise PasswordPolicyError(reasons)


def hash_password(password: str) -> str:
    """Argon2id hash (PHC string). Call validate_password() first for new passwords."""
    pw = _normalise_password(password)
    if len(pw) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError([f"must be at most {PASSWORD_MAX_LENGTH} characters"])
    return _argon2.hash(pw)


def _legacy_bcrypt_verify(password: str, hashed: str) -> bool:
    # Mirrors app/core/passwords.py: bcrypt over the raw SHA-256 digest.
    try:
        return bcrypt.checkpw(hashlib.sha256(password.encode("utf-8")).digest(), hashed.encode("utf-8"))
    except ValueError:
        return False


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant-shape check: always does one full hash computation."""
    if not isinstance(password, str) or len(password) > PASSWORD_MAX_LENGTH * 4:
        password = ""
        hashed = None
    if not hashed:
        try:
            _argon2.verify(_DUMMY_HASH, password or "x")
        except VerificationError:
            pass
        return False
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        return _legacy_bcrypt_verify(password, hashed)
    try:
        return _argon2.verify(hashed, _normalise_password(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True for legacy bcrypt hashes and Argon2 hashes with outdated parameters."""
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        return True
    try:
        return _argon2.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


# ═════════════════════════════════════════════════════════════════════════════
# Access tokens (JWT)
# ═════════════════════════════════════════════════════════════════════════════

_JWT_ALGORITHM = "HS256"
_JWT_KID = "v1"
_JWT_LEEWAY_S = 10
_REQUIRED_CLAIMS = ["iss", "aud", "sub", "tid", "sid", "jti", "iat", "nbf", "exp", "typ"]


class TokenError(Exception):
    """An access or refresh token is malformed, expired or not ours."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    token_id: str
    issued_at: datetime
    expires_at: datetime
    scopes: frozenset[str]


def issue_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    scopes: frozenset[str] | set[str] | list[str],
    cfg: AxonSettings | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Signed access token and its expiry.

    ``scope`` in the token is informational for clients; the server always
    re-reads the live scopes of the session (axon.resolve_session).
    """
    cfg = cfg or settings
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    exp = now + timedelta(seconds=cfg.auth_access_ttl_s)
    payload = {
        "iss": cfg.auth_jwt_issuer,
        "aud": cfg.auth_jwt_audience,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "sid": str(session_id),
        "jti": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
        "scope": " ".join(sorted(scopes)),
    }
    token = jwt.encode(payload, derive_key(PURPOSE_ACCESS_TOKEN, cfg), algorithm=_JWT_ALGORITHM,
                       headers={"kid": _JWT_KID, "typ": "JWT"})
    return token, exp


def decode_access_token(token: str, *, cfg: AxonSettings | None = None) -> AccessClaims:
    """Verify signature, issuer, audience, lifetime and shape; raise TokenError otherwise."""
    cfg = cfg or settings
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise TokenError("malformed token")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise TokenError("malformed token") from None
    if header.get("alg") != _JWT_ALGORITHM or header.get("kid") != _JWT_KID:
        raise TokenError("unexpected token header")
    try:
        claims = jwt.decode(
            token,
            derive_key(PURPOSE_ACCESS_TOKEN, cfg),
            algorithms=[_JWT_ALGORITHM],
            audience=cfg.auth_jwt_audience,
            issuer=cfg.auth_jwt_issuer,
            leeway=_JWT_LEEWAY_S,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("token expired") from None
    except jwt.PyJWTError:
        raise TokenError("invalid token") from None
    if claims.get("typ") != "access":
        raise TokenError("not an access token")
    try:
        scope_str = claims.get("scope", "")
        if not isinstance(scope_str, str):
            raise TypeError
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(claims["tid"]),
            session_id=uuid.UUID(claims["sid"]),
            token_id=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(int(claims["iat"]), timezone.utc),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), timezone.utc),
            scopes=frozenset(scope_str.split()),
        )
    except (TypeError, ValueError, KeyError):
        raise TokenError("invalid token claims") from None


# ═════════════════════════════════════════════════════════════════════════════
# Refresh tokens
# ═════════════════════════════════════════════════════════════════════════════

_REFRESH_RE = re.compile(r"^axr_[A-Za-z0-9_-]{43}$")


def new_refresh_token(cfg: AxonSettings | None = None) -> tuple[str, bytes]:
    """(token for the client, digest for the database)."""
    token = "axr_" + secrets.token_urlsafe(32)
    return token, hash_refresh_token(token, cfg)


def hash_refresh_token(token: str, cfg: AxonSettings | None = None) -> bytes:
    if not isinstance(token, str) or not _REFRESH_RE.match(token):
        raise TokenError("malformed refresh token")
    return _hmac256(derive_key(PURPOSE_REFRESH_TOKEN, cfg), token)


# ═════════════════════════════════════════════════════════════════════════════
# API keys
# ═════════════════════════════════════════════════════════════════════════════

_API_KEY_RE = re.compile(r"^(axk_[A-Za-z0-9]{12})_([A-Za-z0-9_-]{43})$")
_ALNUM = string.ascii_letters + string.digits


class ApiKeyFormatError(ValueError):
    """The string is not an Axon API key."""


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    plaintext: str  # shown to the user exactly once
    prefix: str     # stored, used for lookup and display
    digest: bytes   # stored (axon.api_keys.key_hash)

    def __repr__(self) -> str:  # never print the secret
        return f"GeneratedApiKey(prefix={self.prefix!r})"


def generate_api_key(cfg: AxonSettings | None = None) -> GeneratedApiKey:
    prefix = "axk_" + "".join(secrets.choice(_ALNUM) for _ in range(12))
    plaintext = f"{prefix}_{secrets.token_urlsafe(32)}"
    return GeneratedApiKey(plaintext=plaintext, prefix=prefix, digest=hash_api_key(plaintext, cfg))


def parse_api_key(key: str) -> str:
    """The lookup prefix of a well-formed key; ApiKeyFormatError otherwise."""
    if not isinstance(key, str):
        raise ApiKeyFormatError("not an api key")
    m = _API_KEY_RE.match(key)
    if not m:
        raise ApiKeyFormatError("not an api key")
    return m.group(1)


def hash_api_key(key: str, cfg: AxonSettings | None = None) -> bytes:
    parse_api_key(key)
    return _hmac256(derive_key(PURPOSE_API_KEY, cfg), key)


def hash_api_key_hex(key: str, cfg: AxonSettings | None = None) -> str:
    """64-char hex form of the digest, for VARCHAR columns (api_keys.hashed_key)."""
    return hash_api_key(key, cfg).hex()


def api_key_matches(key: str, stored_digest: bytes | str, cfg: AxonSettings | None = None) -> bool:
    """Constant-time check against a stored digest (raw bytes or hex string)."""
    try:
        candidate = hash_api_key(key, cfg)
    except ApiKeyFormatError:
        return False
    if isinstance(stored_digest, str):
        try:
            stored_digest = bytes.fromhex(stored_digest)
        except ValueError:
            return False
    return hmac.compare_digest(candidate, bytes(stored_digest))


# ═════════════════════════════════════════════════════════════════════════════
# Webhook signatures
# ═════════════════════════════════════════════════════════════════════════════

SIGNATURE_HEADER = "X-Axon-Signature"
DELIVERY_HEADER = "X-Axon-Delivery"
_DELIVERY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
_MAX_SIGNATURE_HEADER = 1024
_MAX_SIGNATURES = 5


class WebhookVerificationError(Exception):
    """The delivery is unsigned, badly signed, stale or malformed."""


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _signed_payload(timestamp: int, delivery_id: str, body: bytes) -> bytes:
    return f"{timestamp}.{delivery_id}.".encode("ascii") + body


def sign_webhook(secret: str, *, delivery_id: str, body: bytes, timestamp: int | None = None) -> str:
    """Header value a sender puts in X-Axon-Signature."""
    if not _DELIVERY_RE.match(delivery_id):
        raise WebhookVerificationError("invalid delivery id")
    ts = int(time.time()) if timestamp is None else int(timestamp)
    sig = hmac.new(secret.encode("utf-8"), _signed_payload(ts, delivery_id, body), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    if not header or len(header) > _MAX_SIGNATURE_HEADER:
        raise WebhookVerificationError("missing or oversized signature header")
    timestamp: int | None = None
    sigs: list[str] = []
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            raise WebhookVerificationError("malformed signature header")
        if key == "t":
            if timestamp is not None or not value.isdigit() or len(value) > 12:
                raise WebhookVerificationError("malformed timestamp")
            timestamp = int(value)
        elif key == "v1":
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise WebhookVerificationError("malformed signature")
            sigs.append(value)
        # Unknown schemes (v0, future v2) are ignored, never trusted.
    if timestamp is None or not sigs:
        raise WebhookVerificationError("signature header needs t= and v1=")
    if len(sigs) > _MAX_SIGNATURES:
        raise WebhookVerificationError("too many signatures")
    return timestamp, sigs


def verify_webhook_signature(
    secrets_: str | list[str],
    *,
    header: str,
    delivery_id: str,
    body: bytes,
    tolerance_s: int = 300,
    now: float | None = None,
) -> int:
    """Return the signed timestamp, or raise WebhookVerificationError.

    ``secrets_`` may hold the current and the previous secret while a
    rotation is in progress; any one of them may match any v1 signature.
    """
    if not isinstance(delivery_id, str) or not _DELIVERY_RE.match(delivery_id):
        raise WebhookVerificationError("invalid delivery id")
    timestamp, sigs = _parse_signature_header(header)
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance_s:
        raise WebhookVerificationError("timestamp outside tolerance")
    payload = _signed_payload(timestamp, delivery_id, body)
    keys = [secrets_] if isinstance(secrets_, str) else list(secrets_)
    ok = False
    for secret in keys:
        if not secret:
            continue
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        for sig in sigs:
            # Evaluate every pair so timing does not reveal which one matched.
            ok |= hmac.compare_digest(expected, sig)
    if not ok:
        raise WebhookVerificationError("signature mismatch")
    return timestamp
