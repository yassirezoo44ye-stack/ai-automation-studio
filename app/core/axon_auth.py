"""
Axon authentication and authorization (organization-scoped, schema ``axon``).

Flows
-----
* register      new organization + its first admin (axon.provision_organization),
                then a session.
* login         organization slug + e-mail + password -> session. E-mails are
                unique per organization, so the slug is always required.
* refresh       consumes the refresh token and issues the next one in the same
                family (rotation). Re-presenting a consumed token is treated
                as theft: the whole family (= session) is revoked.
* logout        revokes this session; logout-all revokes every session.
* password      change revokes every session and returns a fresh one.
* API keys      organization-bound machine credentials; scopes capped by the
                creator's own scopes (checked here and again by a DB trigger).
* webhooks      per-endpoint signing secret (encrypted at rest), timestamped
                HMAC signature, replay ledger.

Every authenticated request re-reads the caller's *live* scopes from the
database (role -> axon.role_scope_list, or the API key row), and checks that
the session family is still open, so revoking a session, deactivating a user
or changing a role takes effect on the next request rather than when the
access token expires. The result is a ``TenantContext`` stored on
``request.state`` for app/core/db.py's tenant-scoped sessions; the
organization is never taken from client-supplied headers or bodies.

FastAPI usage::

    from app.core.axon_auth import Principal, requires, tenant_db

    @router.post("/workflows/{wid}/run")
    async def run(wid: UUID,
                  principal: Principal = Depends(requires("workflows:execute")),
                  session: AsyncSession = Depends(tenant_db)):
        ...
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import axon_security as sec
from app.core.config import (
    AxonSettings,
    ConfigurationError,
    TokenDecryptionError,
    get_token_cipher,
    settings,
)
from app.core.db import (
    REQUEST_TENANT_ATTR,
    Database,
    TenantContext,
    TenantContextError,
    get_database,
)
from app.core.rate_limit import (
    _real_ip,
    check_login_locked_async,
    clear_login_failures_async,
    record_login_failure_async,
)

log = logging.getLogger(__name__)

REQUEST_PRINCIPAL_ATTR = "axon_principal"
WEBHOOK_SECRET_PURPOSE = "webhook:secret"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,98}[a-z0-9])$")


# ═════════════════════════════════════════════════════════════════════════════
# Errors and value objects
# ═════════════════════════════════════════════════════════════════════════════

class AuthError(HTTPException):
    """An HTTP error with a stable machine-readable ``code``.

    It is an HTTPException, so FastAPI renders it without extra handlers:
    ``{"detail": {"code": "...", "message": "..."}}``.
    """

    def __init__(self, status_code: int, code: str, message: str, *,
                 extra: Mapping[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        detail: dict[str, Any] = {"code": code, "message": message}
        if extra:
            detail.update(extra)
        if status_code == status.HTTP_401_UNAUTHORIZED and headers is None:
            headers = {"WWW-Authenticate": 'Bearer realm="axon"'}
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def _unauthorized(code: str = "invalid_token", message: str = "Not authenticated") -> AuthError:
    return AuthError(status.HTTP_401_UNAUTHORIZED, code, message)


def _unprocessable(code: str, message: str, **extra: Any) -> AuthError:
    return AuthError(status.HTTP_422_UNPROCESSABLE_ENTITY, code, message, extra=extra or None)


INVALID_CREDENTIALS = "Invalid organization, e-mail or password"


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. ``tenant`` is what the database layer uses."""

    kind: Literal["user", "api_key"]
    tenant: TenantContext
    session_id: uuid.UUID | None = None  # refresh-token family, users only

    @property
    def organization_id(self) -> uuid.UUID:
        return self.tenant.tenant_id

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.tenant.user_id

    @property
    def api_key_id(self) -> uuid.UUID | None:
        return self.tenant.api_key_id

    @property
    def scopes(self) -> frozenset[str]:
        return self.tenant.scopes


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_token: str = field(repr=False)
    refresh_expires_at: datetime
    session_id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    scopes: frozenset[str]
    token_type: str = "Bearer"

    def as_response(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "token_type": self.token_type,
            "access_token": self.access_token,
            "expires_in": max(0, int((self.access_expires_at - now).total_seconds())),
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "organization_id": str(self.organization_id),
            "scopes": sorted(self.scopes),
        }


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Where a request came from; recorded on refresh tokens and audit events."""

    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> ClientInfo:
        try:
            ip = str(ipaddress.ip_address(_real_ip(request)))
        except ValueError:
            ip = None
        ua = request.headers.get("user-agent")
        return cls(ip=ip, user_agent=ua[:512] if ua else None)


@dataclass(frozen=True, slots=True)
class CreatedApiKey:
    id: uuid.UUID
    name: str
    prefix: str
    scopes: tuple[str, ...]
    expires_at: datetime | None
    created_at: datetime
    plaintext: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CreatedWebhook:
    id: uuid.UUID
    name: str
    tolerance_seconds: int
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    endpoint_id: uuid.UUID
    organization_id: uuid.UUID
    delivery_id: str
    signed_at: int


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _db(db: Database | None) -> Database:
    return db or get_database()


def _cfg(cfg: AxonSettings | None) -> AxonSettings:
    return cfg or settings


def normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 255 or not _EMAIL_RE.match(value):
        raise _unprocessable("invalid_email", "Invalid e-mail address")
    return value


def normalise_slug(slug: str) -> str:
    value = (slug or "").strip().lower()
    if not _SLUG_RE.match(value):
        raise _unprocessable("invalid_slug", "Organization slug: 3-100 lowercase letters, digits or dashes")
    return value


def _refresh_hash(token: str, cfg: AxonSettings) -> str:
    return sec.hash_refresh_token(token, cfg).hex()


async def _audit(db: Database, ctx: TenantContext, action: str, *, client: ClientInfo | None = None,
                 resource_type: str | None = None, resource_id: str | None = None,
                 metadata: Mapping[str, Any] | None = None) -> None:
    """Append to axon.audit_events in its own transaction.

    Failures are logged, never raised: an audit outage must not lock users
    out, but it must be visible in the logs.
    """
    try:
        async with db.tenant_session(ctx) as s:
            await s.execute(
                text(
                    "INSERT INTO axon.audit_events (organization_id, actor_user_id, actor_api_key_id, action, "
                    "resource_type, resource_id, ip_address, user_agent, metadata) "
                    "VALUES (:o, :u, :k, :a, :rt, :rid, CAST(:ip AS inet), :ua, CAST(:m AS jsonb))"
                ),
                {
                    "o": ctx.tenant_id, "u": ctx.user_id, "k": ctx.api_key_id, "a": action,
                    "rt": resource_type, "rid": resource_id,
                    "ip": client.ip if client else None,
                    "ua": client.user_agent if client else None,
                    "m": json.dumps(dict(metadata or {}), default=str),
                },
            )
    except Exception:
        log.warning("axon auth: audit write failed for %s", action, exc_info=True)


async def _role_scopes(s: AsyncSession, organization_id: uuid.UUID, role: str) -> frozenset[str]:
    scopes = (await s.execute(
        text("SELECT axon.role_scope_list(:o, :r)"), {"o": organization_id, "r": role},
    )).scalar()
    return frozenset(scopes or ())


async def _start_session(
    db: Database, *, organization_id: uuid.UUID, user_id: uuid.UUID, scopes: frozenset[str],
    client: ClientInfo, cfg: AxonSettings, extra_sql: tuple[str, dict[str, Any]] | None = None,
) -> TokenPair:
    """New refresh-token family + first token, and an access token for it."""
    family_id = uuid.uuid4()
    refresh, _ = sec.new_refresh_token(cfg)
    now = datetime.now(timezone.utc)
    refresh_exp = now + timedelta(seconds=cfg.auth_refresh_ttl_s)
    ctx = TenantContext(organization_id, user_id, scopes)
    async with db.tenant_session(ctx) as s:
        if extra_sql:
            await s.execute(text(extra_sql[0]), extra_sql[1])
        await s.execute(
            text(
                "INSERT INTO axon.refresh_tokens (organization_id, user_id, family_id, token_hash, expires_at, "
                "ip_address, user_agent) VALUES (:o, :u, :f, :h, :exp, CAST(:ip AS inet), :ua)"
            ),
            {"o": organization_id, "u": user_id, "f": family_id, "h": _refresh_hash(refresh, cfg),
             "exp": refresh_exp, "ip": client.ip, "ua": client.user_agent},
        )
    access, access_exp = sec.issue_access_token(
        user_id=user_id, tenant_id=organization_id, session_id=family_id, scopes=scopes, cfg=cfg,
    )
    return TokenPair(access_token=access, access_expires_at=access_exp, refresh_token=refresh,
                     refresh_expires_at=refresh_exp, session_id=family_id, user_id=user_id,
                     organization_id=organization_id, scopes=scopes)


async def _revoke_family(db: Database, ctx: TenantContext, family_id: uuid.UUID, reason: str) -> int:
    async with db.tenant_session(ctx) as s:
        res = await s.execute(
            text(
                "UPDATE axon.refresh_tokens SET revoked_at = now(), revoked_reason = :r "
                "WHERE family_id = :f AND user_id = :u AND revoked_at IS NULL"
            ),
            {"r": reason, "f": family_id, "u": ctx.user_id},
        )
        return res.rowcount or 0


async def _revoke_user(db: Database, ctx: TenantContext, reason: str) -> int:
    async with db.tenant_session(ctx) as s:
        res = await s.execute(
            text(
                "UPDATE axon.refresh_tokens SET revoked_at = now(), revoked_reason = :r "
                "WHERE user_id = :u AND revoked_at IS NULL"
            ),
            {"r": reason, "u": ctx.user_id},
        )
        return res.rowcount or 0


def _password_or_422(password: str, email: str) -> None:
    try:
        sec.validate_password(password, email=email)
    except sec.PasswordPolicyError as exc:
        raise _unprocessable("weak_password", "Password rejected", reasons=exc.reasons) from None


# ═════════════════════════════════════════════════════════════════════════════
# Registration, login, refresh, logout, password
# ═════════════════════════════════════════════════════════════════════════════

async def register(
    *, organization_name: str, organization_slug: str, email: str, password: str,
    full_name: str | None = None, client: ClientInfo | None = None,
    db: Database | None = None, cfg: AxonSettings | None = None,
) -> TokenPair:
    """Create an organization and its first admin; return a session for them."""
    cfg, db, client = _cfg(cfg), _db(db), client or ClientInfo()
    if not cfg.auth_allow_signup:
        raise AuthError(status.HTTP_403_FORBIDDEN, "signup_disabled", "Sign-up is disabled")
    email = normalise_email(email)
    slug = normalise_slug(organization_slug)
    name = (organization_name or "").strip()
    if not 1 <= len(name) <= 255:
        raise _unprocessable("invalid_name", "Organization name: 1-255 characters")
    _password_or_422(password, email)
    pw_hash = sec.hash_password(password)
    try:
        async with db.system_session("signup: provision organization") as s:
            row = (await s.execute(
                text("SELECT organization_id, user_id FROM axon.provision_organization(:s, :n, :e, :h, :f)"),
                {"s": slug, "n": name, "e": email, "h": pw_hash, "f": (full_name or "").strip()[:255] or None},
            )).mappings().one()
            scopes = await _role_scopes(s, row["organization_id"], "admin")
    except IntegrityError:
        raise AuthError(status.HTTP_409_CONFLICT, "slug_taken", "That organization slug is already in use") from None
    pair = await _start_session(db, organization_id=row["organization_id"], user_id=row["user_id"],
                                scopes=scopes, client=client, cfg=cfg)
    await _audit(db, TenantContext(pair.organization_id, pair.user_id, scopes), "auth.register",
                 client=client, resource_type="organization", resource_id=str(pair.organization_id))
    return pair


async def login(
    *, organization_slug: str, email: str, password: str, client: ClientInfo | None = None,
    db: Database | None = None, cfg: AxonSettings | None = None,
) -> TokenPair:
    cfg, db, client = _cfg(cfg), _db(db), client or ClientInfo()
    try:
        slug, email = normalise_slug(organization_slug), normalise_email(email)
    except AuthError:
        sec.verify_password(password or "", None)  # same work as a real attempt
        raise _unauthorized("invalid_credentials", INVALID_CREDENTIALS) from None
    lock_key = f"{slug}/{email}"
    if await check_login_locked_async(lock_key):
        raise AuthError(status.HTTP_429_TOO_MANY_REQUESTS, "account_locked",
                        "Too many failed attempts; try again later", headers={"Retry-After": "900"})

    async with db.system_session("login: pre-auth lookup") as s:
        row = (await s.execute(
            text("SELECT user_id, organization_id, hashed_password, role, is_active, mfa_enabled, scopes "
                 "FROM axon.find_login_user(:s, :e)"),
            {"s": slug, "e": email},
        )).mappings().first()
    ok = sec.verify_password(password, row["hashed_password"] if row else None)
    if not ok or not row or not row["is_active"]:
        await record_login_failure_async(lock_key)
        raise _unauthorized("invalid_credentials", INVALID_CREDENTIALS)
    if row["mfa_enabled"]:
        # Fail closed until the TOTP step exists: never skip a second factor.
        raise _unauthorized("mfa_required", "This account needs multi-factor sign-in, which is not available yet")

    scopes = frozenset(row["scopes"] or ())
    rehash = sec.hash_password(password) if sec.password_needs_rehash(row["hashed_password"]) else None
    pair = await _start_session(
        db, organization_id=row["organization_id"], user_id=row["user_id"], scopes=scopes, client=client, cfg=cfg,
        extra_sql=(
            ("UPDATE axon.users SET last_login_at = now(), hashed_password = coalesce(:h, hashed_password) "
            "WHERE id = :u"),
            {"h": rehash, "u": row["user_id"]},
        ),
    )
    await clear_login_failures_async(lock_key)
    await _audit(db, TenantContext(pair.organization_id, pair.user_id, scopes), "auth.login", client=client,
                 resource_type="session", resource_id=str(pair.session_id))
    return pair


async def refresh(
    refresh_token: str, *, client: ClientInfo | None = None,
    db: Database | None = None, cfg: AxonSettings | None = None,
) -> TokenPair:
    """Rotate: the presented token is consumed and a new pair is returned."""
    cfg, db, client = _cfg(cfg), _db(db), client or ClientInfo()
    try:
        token_hash = _refresh_hash(refresh_token, cfg)
    except sec.TokenError:
        raise _unauthorized("invalid_refresh_token", "Invalid refresh token") from None

    async with db.system_session("refresh: pre-auth lookup") as s:
        row = (await s.execute(
            text("SELECT token_id, organization_id, user_id, family_id, expires_at, used_at, revoked_at, "
                 "user_is_active FROM axon.find_refresh_token(:h)"),
            {"h": token_hash},
        )).mappings().first()
    if row is None:
        raise _unauthorized("invalid_refresh_token", "Invalid refresh token")
    ctx = TenantContext(row["organization_id"], row["user_id"])
    if row["revoked_at"] is not None:
        raise _unauthorized("session_revoked", "Session has been revoked")
    if row["used_at"] is not None:
        await _revoke_family(db, ctx, row["family_id"], "reuse_detected")
        log.warning("axon auth: refresh token reuse, family %s revoked", row["family_id"])
        await _audit(db, ctx, "auth.refresh_reuse_detected", client=client,
                     resource_type="session", resource_id=str(row["family_id"]))
        raise _unauthorized("refresh_token_reused", "Refresh token was already used; session revoked")
    now = datetime.now(timezone.utc)
    if row["expires_at"] <= now:
        raise _unauthorized("refresh_token_expired", "Refresh token expired")
    if not row["user_is_active"]:
        await _revoke_family(db, ctx, row["family_id"], "access_lost")
        raise _unauthorized("session_revoked", "Session has been revoked")

    new_token, _ = sec.new_refresh_token(cfg)
    outcome = "ok"
    async with db.tenant_session(ctx) as s:
        live = (await s.execute(
            text(
                "SELECT axon.role_scope_list(u.organization_id, u.role) AS scopes, "
                "       (SELECT min(r.created_at) FROM axon.refresh_tokens r WHERE r.family_id = :f) AS started "
                "FROM axon.users u JOIN axon.organizations o ON o.id = u.organization_id "
                "WHERE u.id = :u AND u.is_active AND o.is_active"
            ),
            {"u": row["user_id"], "f": row["family_id"]},
        )).mappings().first()
        if live is None:
            outcome = "access_lost"
        elif live["started"] + timedelta(seconds=cfg.auth_session_max_age_s) <= now:
            outcome = "session_expired"
        else:
            # Conditional update = the atomic "consume once": of two concurrent
            # refreshes with the same token, exactly one sees a row here.
            consumed = (await s.execute(
                text("UPDATE axon.refresh_tokens SET used_at = now() "
                     "WHERE id = :id AND used_at IS NULL AND revoked_at IS NULL RETURNING id"),
                {"id": row["token_id"]},
            )).scalar()
            if consumed is None:
                outcome = "reuse_detected"
            else:
                session_end = live["started"] + timedelta(seconds=cfg.auth_session_max_age_s)
                refresh_exp = min(now + timedelta(seconds=cfg.auth_refresh_ttl_s), session_end)
                await s.execute(
                    text(
                        "INSERT INTO axon.refresh_tokens (organization_id, user_id, family_id, token_hash, "
                        "expires_at, ip_address, user_agent) VALUES (:o, :u, :f, :h, :exp, CAST(:ip AS inet), :ua)"
                    ),
                    {"o": row["organization_id"], "u": row["user_id"], "f": row["family_id"],
                     "h": _refresh_hash(new_token, cfg), "exp": refresh_exp,
                     "ip": client.ip, "ua": client.user_agent},
                )
    if outcome != "ok":
        reason = {"access_lost": "access_lost", "session_expired": "expired", "reuse_detected": "reuse_detected"}
        await _revoke_family(db, ctx, row["family_id"], reason[outcome])
        if outcome == "reuse_detected":
            await _audit(db, ctx, "auth.refresh_reuse_detected", client=client,
                         resource_type="session", resource_id=str(row["family_id"]))
            raise _unauthorized("refresh_token_reused", "Refresh token was already used; session revoked")
        raise _unauthorized("session_revoked" if outcome == "access_lost" else "session_expired",
                            "Session is no longer valid")

    scopes = frozenset(live["scopes"] or ())
    access, access_exp = sec.issue_access_token(
        user_id=row["user_id"], tenant_id=row["organization_id"], session_id=row["family_id"],
        scopes=scopes, cfg=cfg,
    )
    return TokenPair(access_token=access, access_expires_at=access_exp, refresh_token=new_token,
                     refresh_expires_at=refresh_exp, session_id=row["family_id"], user_id=row["user_id"],
                     organization_id=row["organization_id"], scopes=scopes)


def _require_user(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if principal.kind != "user" or principal.user_id is None or principal.session_id is None:
        raise AuthError(status.HTTP_403_FORBIDDEN, "user_required", "This action needs a signed-in user")
    return principal.user_id, principal.session_id


async def logout(principal: Principal, *, client: ClientInfo | None = None, db: Database | None = None) -> None:
    db = _db(db)
    _, family_id = _require_user(principal)
    await _revoke_family(db, principal.tenant, family_id, "logout")
    await _audit(db, principal.tenant, "auth.logout", client=client,
                 resource_type="session", resource_id=str(family_id))


async def logout_all(principal: Principal, *, client: ClientInfo | None = None, db: Database | None = None) -> int:
    db = _db(db)
    _require_user(principal)
    n = await _revoke_user(db, principal.tenant, "logout_all")
    await _audit(db, principal.tenant, "auth.logout_all", client=client, metadata={"tokens_revoked": n})
    return n


async def change_password(
    principal: Principal, *, current_password: str, new_password: str, client: ClientInfo | None = None,
    db: Database | None = None, cfg: AxonSettings | None = None,
) -> TokenPair:
    """Verify, replace the hash, revoke every session, return a fresh session."""
    cfg, db, client = _cfg(cfg), _db(db), client or ClientInfo()
    user_id, _ = _require_user(principal)
    async with db.tenant_session(principal.tenant) as s:
        me = (await s.execute(
            text("SELECT email, hashed_password FROM axon.users WHERE id = :u AND is_active"), {"u": user_id},
        )).mappings().first()
    if me is None:
        raise _unauthorized("session_revoked", "Session is no longer valid")
    lock_key = f"pwchange/{user_id}"
    if await check_login_locked_async(lock_key):
        raise AuthError(status.HTTP_429_TOO_MANY_REQUESTS, "account_locked",
                        "Too many failed attempts; try again later", headers={"Retry-After": "900"})
    if not sec.verify_password(current_password, me["hashed_password"]):
        await record_login_failure_async(lock_key)
        raise _unauthorized("invalid_credentials", "Current password is wrong")
    if current_password == new_password:
        raise _unprocessable("weak_password", "Password rejected", reasons=["must differ from the current password"])
    _password_or_422(new_password, me["email"])
    new_hash = sec.hash_password(new_password)
    async with db.tenant_session(principal.tenant) as s:
        res = await s.execute(text("UPDATE axon.users SET hashed_password = :h WHERE id = :u"),
                              {"h": new_hash, "u": user_id})
        if res.rowcount != 1:
            raise _unauthorized("session_revoked", "Session is no longer valid")
    await _revoke_user(db, principal.tenant, "password_changed")
    await clear_login_failures_async(lock_key)
    pair = await _start_session(db, organization_id=principal.organization_id, user_id=user_id,
                                scopes=principal.scopes, client=client, cfg=cfg)
    await _audit(db, principal.tenant, "auth.password_changed", client=client)
    return pair


# ═════════════════════════════════════════════════════════════════════════════
# Request authentication
# ═════════════════════════════════════════════════════════════════════════════

async def authenticate_access_token(token: str, *, db: Database | None = None,
                                    cfg: AxonSettings | None = None) -> Principal:
    try:
        claims = sec.decode_access_token(token, cfg=cfg)
    except sec.TokenError as exc:
        code = "token_expired" if str(exc) == "token expired" else "invalid_token"
        raise _unauthorized(code, "Invalid or expired access token") from None
    probe = TenantContext(claims.tenant_id, claims.user_id)
    async with _db(db).tenant_session(probe) as s:
        live = (await s.execute(
            text(
                "SELECT axon.role_scope_list(u.organization_id, u.role) "
                "FROM axon.users u JOIN axon.organizations o ON o.id = u.organization_id "
                "WHERE u.id = :u AND u.organization_id = :o AND u.is_active AND o.is_active "
                "  AND EXISTS (SELECT 1 FROM axon.refresh_tokens r "
                "               WHERE r.family_id = :f AND r.user_id = u.id "
                "                 AND r.revoked_at IS NULL AND r.expires_at > now())"
            ),
            {"u": claims.user_id, "o": claims.tenant_id, "f": claims.session_id},
        )).first()
    if live is None:
        raise _unauthorized("session_revoked", "Session is no longer valid")
    ctx = TenantContext(claims.tenant_id, claims.user_id, frozenset(live[0] or ()))
    return Principal(kind="user", tenant=ctx, session_id=claims.session_id)


async def authenticate_api_key(key: str, *, db: Database | None = None,
                               cfg: AxonSettings | None = None) -> Principal:
    db = _db(db)
    try:
        hashed = sec.hash_api_key_hex(key, cfg)
    except sec.ApiKeyFormatError:
        raise _unauthorized("invalid_api_key", "Invalid API key") from None
    async with db.system_session("api key: pre-auth lookup") as s:
        row = (await s.execute(
            text("SELECT api_key_id, organization_id, user_id, scopes FROM axon.lookup_api_key(:h)"), {"h": hashed},
        )).mappings().first()
    if row is None:
        raise _unauthorized("invalid_api_key", "Invalid API key")
    ctx = TenantContext(row["organization_id"], row["user_id"], frozenset(row["scopes"] or ()),
                        api_key_id=row["api_key_id"])
    try:
        async with db.tenant_session(ctx) as s:
            await s.execute(text("SELECT axon.touch_api_key(:k)"), {"k": row["api_key_id"]})
    except DBAPIError:
        # Bookkeeping only; never fail an otherwise valid request over it.
        log.warning("axon auth: could not stamp last_used_at of api key %s", row["api_key_id"], exc_info=True)
    return Principal(kind="api_key", tenant=ctx)


def _credentials(request: Request) -> tuple[Literal["bearer", "api_key"], str]:
    authz = request.headers.get("authorization", "").strip()
    x_key = request.headers.get("x-api-key", "").strip()
    if authz and x_key:
        raise _unauthorized("ambiguous_credentials", "Send either Authorization or X-API-Key, not both")
    if x_key:
        return "api_key", x_key
    scheme, _, cred = authz.partition(" ")
    cred = cred.strip()
    if not cred:
        raise _unauthorized("missing_credentials", "Not authenticated")
    scheme = scheme.lower()
    if scheme == "apikey" or (scheme == "bearer" and cred.startswith("axk_")):
        return "api_key", cred
    if scheme == "bearer":
        return "bearer", cred
    raise _unauthorized("unsupported_scheme", "Unsupported authorization scheme")


async def authenticate(request: Request) -> Principal:
    """FastAPI dependency: verify the caller and bind their organization to the request.

    Accepts ``Authorization: Bearer <access token>``, ``Authorization: ApiKey
    <key>``, ``Authorization: Bearer axk_...`` or ``X-API-Key: <key>``.
    Resolved once per request; later dependencies reuse the result.
    """
    cached = getattr(request.state, REQUEST_PRINCIPAL_ATTR, None)
    if isinstance(cached, Principal):
        return cached
    kind, cred = _credentials(request)
    principal = await (authenticate_access_token(cred) if kind == "bearer" else authenticate_api_key(cred))
    setattr(request.state, REQUEST_PRINCIPAL_ATTR, principal)
    setattr(request.state, REQUEST_TENANT_ATTR, principal.tenant)
    return principal


AuthenticatedDep = Annotated[Principal, Depends(authenticate)]


def requires(*scopes: str):
    """``Depends(requires("workflows:execute"))`` → the Principal, or 403."""
    TenantContext(uuid.UUID(int=0), scopes=frozenset(scopes))  # rejects malformed declarations at import

    async def _dep(principal: AuthenticatedDep) -> Principal:
        missing = [s for s in scopes if not principal.tenant.has_scope(s)]
        if missing:
            raise AuthError(status.HTTP_403_FORBIDDEN, "insufficient_scope", "Insufficient scope",
                            extra={"missing": missing})
        return principal

    return _dep


async def require_user(principal: AuthenticatedDep) -> Principal:
    """Rejects API keys for actions that belong to a person (password, sessions)."""
    _require_user(principal)
    return principal


UserDep = Annotated[Principal, Depends(require_user)]


async def tenant_db(principal: AuthenticatedDep) -> AsyncIterator[AsyncSession]:
    """A database session confined to the caller's organization and scopes."""
    async with get_database().tenant_session(principal.tenant) as session:
        yield session


# ═════════════════════════════════════════════════════════════════════════════
# API keys
# ═════════════════════════════════════════════════════════════════════════════

def _db_error(exc: DBAPIError) -> AuthError:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "42501":
        return AuthError(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed")
    if sqlstate in {"23514", "23505", "22P02", "23503"}:
        return _unprocessable("invalid_request", "Invalid request")
    raise exc


async def create_api_key(
    principal: Principal, *, name: str, scopes: list[str], expires_at: datetime | None = None,
    client: ClientInfo | None = None, db: Database | None = None, cfg: AxonSettings | None = None,
) -> CreatedApiKey:
    db = _db(db)
    if principal.kind != "user" or principal.user_id is None:
        raise AuthError(status.HTTP_403_FORBIDDEN, "user_required", "API keys are created by signed-in users")
    if not principal.tenant.has_scope("api_keys:manage"):
        raise AuthError(status.HTTP_403_FORBIDDEN, "insufficient_scope", "Insufficient scope",
                        extra={"missing": ["api_keys:manage"]})
    name = (name or "").strip()
    if not 1 <= len(name) <= 100:
        raise _unprocessable("invalid_name", "Key name: 1-100 characters")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            raise _unprocessable("invalid_expiry", "expires_at needs a timezone")
        if expires_at <= datetime.now(timezone.utc):
            raise _unprocessable("invalid_expiry", "expires_at is in the past")
    clean = tuple(sorted(set(scopes)))
    if not clean:
        raise _unprocessable("invalid_scope", "Give the key at least one scope")
    try:
        TenantContext(principal.organization_id, scopes=frozenset(clean))
    except TenantContextError:
        raise _unprocessable("invalid_scope", "Invalid scope") from None
    over = [s for s in clean if not principal.tenant.has_scope(s)]
    if over:
        raise AuthError(status.HTTP_403_FORBIDDEN, "scope_escalation", "Cannot grant scopes you do not hold",
                        extra={"scopes": over})
    key = sec.generate_api_key(cfg)
    try:
        async with db.tenant_session(principal.tenant) as s:
            row = (await s.execute(
                text(
                    "INSERT INTO axon.api_keys (organization_id, user_id, name, key_prefix, hashed_key, scopes, "
                    "expires_at) VALUES (:o, :u, :n, :p, :h, :sc, :exp) RETURNING id, created_at"
                ),
                {"o": principal.organization_id, "u": principal.user_id, "n": name, "p": key.prefix,
                 "h": key.digest.hex(), "sc": list(clean), "exp": expires_at},
            )).mappings().one()
    except DBAPIError as exc:
        raise _db_error(exc) from None
    await _audit(db, principal.tenant, "api_key.created", client=client, resource_type="api_key",
                 resource_id=str(row["id"]), metadata={"scopes": list(clean), "prefix": key.prefix})
    return CreatedApiKey(id=row["id"], name=name, prefix=key.prefix, scopes=clean, expires_at=expires_at,
                         created_at=row["created_at"], plaintext=key.plaintext)


async def list_api_keys(principal: Principal, *, db: Database | None = None) -> list[dict[str, Any]]:
    async with _db(db).tenant_session(principal.tenant) as s:
        rows = (await s.execute(text(
            "SELECT id, name, key_prefix, scopes, user_id, expires_at, is_active, last_used_at, created_at "
            "FROM axon.api_keys ORDER BY created_at DESC"
        ))).mappings().all()
    return [dict(r) for r in rows]


async def revoke_api_key(principal: Principal, key_id: uuid.UUID, *, client: ClientInfo | None = None,
                         db: Database | None = None) -> bool:
    db = _db(db)
    async with db.tenant_session(principal.tenant) as s:
        hit = (await s.execute(
            text("UPDATE axon.api_keys SET is_active = false WHERE id = :k AND is_active RETURNING id"),
            {"k": key_id},
        )).scalar()
    if hit:
        await _audit(db, principal.tenant, "api_key.revoked", client=client, resource_type="api_key",
                     resource_id=str(key_id))
    return hit is not None


# ═════════════════════════════════════════════════════════════════════════════
# Inbound webhooks
# ═════════════════════════════════════════════════════════════════════════════

def _cipher():
    try:
        return get_token_cipher()
    except ConfigurationError:
        raise AuthError(status.HTTP_503_SERVICE_UNAVAILABLE, "encryption_unavailable",
                        "Secret encryption is not configured") from None


async def create_webhook_endpoint(
    principal: Principal, *, name: str, tolerance_seconds: int = 300,
    client: ClientInfo | None = None, db: Database | None = None,
) -> CreatedWebhook:
    db = _db(db)
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise _unprocessable("invalid_name", "Webhook name: 1-80 characters")
    if not 30 <= tolerance_seconds <= 900:
        raise _unprocessable("invalid_tolerance", "Tolerance: 30-900 seconds")
    cipher = _cipher()
    secret = sec.generate_webhook_secret()
    try:
        async with db.tenant_session(principal.tenant) as s:
            wid = (await s.execute(
                text(
                    "INSERT INTO axon.webhook_endpoints (organization_id, name, secret_ciphertext, "
                    "tolerance_seconds, created_by) VALUES (:o, :n, :c, :tol, :u) RETURNING id"
                ),
                {"o": principal.organization_id, "n": name, "tol": tolerance_seconds, "u": principal.user_id,
                 "c": cipher.encrypt(secret, tenant_id=principal.organization_id, purpose=WEBHOOK_SECRET_PURPOSE)},
            )).scalar_one()
    except DBAPIError as exc:
        raise _db_error(exc) from None
    await _audit(db, principal.tenant, "webhook.created", client=client, resource_type="webhook_endpoint",
                 resource_id=str(wid))
    return CreatedWebhook(id=wid, name=name, tolerance_seconds=tolerance_seconds, secret=secret)


async def rotate_webhook_secret(principal: Principal, endpoint_id: uuid.UUID, *,
                                client: ClientInfo | None = None, db: Database | None = None) -> str:
    """Replace the signing secret; deliveries signed with the old one stop verifying."""
    db = _db(db)
    cipher = _cipher()
    secret = sec.generate_webhook_secret()
    try:
        async with db.tenant_session(principal.tenant) as s:
            hit = (await s.execute(
                text("UPDATE axon.webhook_endpoints SET secret_ciphertext = :c WHERE id = :w RETURNING id"),
                {"w": endpoint_id,
                 "c": cipher.encrypt(secret, tenant_id=principal.organization_id, purpose=WEBHOOK_SECRET_PURPOSE)},
            )).scalar()
    except DBAPIError as exc:
        raise _db_error(exc) from None
    if hit is None:
        raise AuthError(status.HTTP_404_NOT_FOUND, "not_found", "Webhook endpoint not found")
    await _audit(db, principal.tenant, "webhook.secret_rotated", client=client,
                 resource_type="webhook_endpoint", resource_id=str(endpoint_id))
    return secret


_BAD_SIGNATURE = "Invalid webhook signature"


async def verify_webhook_delivery(
    endpoint_id: uuid.UUID, *, headers: Mapping[str, str], body: bytes,
    db: Database | None = None, now: float | None = None,
) -> WebhookDelivery:
    """Authenticate an inbound delivery and record it in the replay ledger.

    Unknown endpoints and bad signatures get the same 401, so the receiver
    does not reveal which endpoint ids exist. A repeated delivery id is 409.
    """
    db = _db(db)
    lower = {k.lower(): v for k, v in headers.items()}
    delivery_id = lower.get(sec.DELIVERY_HEADER.lower(), "")
    signature = lower.get(sec.SIGNATURE_HEADER.lower(), "")
    async with db.system_session("webhook: pre-auth lookup") as s:
        row = (await s.execute(
            text("SELECT organization_id, secret_ciphertext, tolerance_seconds "
                 "FROM axon.lookup_webhook_endpoint(:w)"),
            {"w": endpoint_id},
        )).mappings().first()
    if row is None:
        raise _unauthorized("invalid_signature", _BAD_SIGNATURE)
    try:
        secret = get_token_cipher().decrypt(row["secret_ciphertext"], tenant_id=row["organization_id"],
                                            purpose=WEBHOOK_SECRET_PURPOSE)
    except (ConfigurationError, TokenDecryptionError):
        log.error("axon webhooks: cannot decrypt the secret of endpoint %s", endpoint_id)
        raise AuthError(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook_unavailable",
                        "Webhook endpoint unavailable") from None
    try:
        signed_at = sec.verify_webhook_signature(
            secret, header=signature, delivery_id=delivery_id, body=body,
            tolerance_s=row["tolerance_seconds"], now=now,
        )
    except sec.WebhookVerificationError:
        raise _unauthorized("invalid_signature", _BAD_SIGNATURE) from None
    try:
        async with db.tenant_session(TenantContext(row["organization_id"])) as s:
            await s.execute(
                text("INSERT INTO axon.webhook_deliveries (endpoint_id, organization_id, delivery_id) "
                     "VALUES (:w, :o, :d)"),
                {"w": endpoint_id, "o": row["organization_id"], "d": delivery_id},
            )
    except IntegrityError:
        raise AuthError(status.HTTP_409_CONFLICT, "replayed_delivery", "Delivery already received") from None
    return WebhookDelivery(endpoint_id=endpoint_id, organization_id=row["organization_id"],
                           delivery_id=delivery_id, signed_at=signed_at)
