"""
Full user authentication router.

Endpoints:
  POST /api/auth/register
  POST /api/auth/login
  POST /api/auth/refresh
  POST /api/auth/logout
  POST /api/auth/logout-all
  GET  /api/auth/verify-email/{token}
  POST /api/auth/resend-verification
  POST /api/auth/forgot-password
  POST /api/auth/reset-password
  GET  /api/auth/me
  PUT  /api/auth/me
  PUT  /api/auth/me/password
  GET  /api/auth/sessions
  DELETE /api/auth/sessions/{session_id}
  DELETE /api/auth/me
"""
import datetime
import secrets
import uuid
from typing import Annotated, Optional

import asyncpg
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, field_validator

from app.core.db import get_pool, write_audit
from app.core.email import send_password_reset_email, send_verification_email
from app.core.rate_limit import make_rate_limit_dep
from app.core.jwt_utils import (
    REFRESH_EXPIRE_DAYS_REMEMBER,
    REFRESH_EXPIRE_DAYS_SESSION,
    decode_access_token,
    make_access_token,
    make_refresh_token,
)
from app.core.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=False)

# 10 attempts per minute per IP on unauthenticated auth endpoints.
# The global 300/min limit in factory.py applies on top of this.
_auth_rl = Depends(make_rate_limit_dep(
    "auth",
    max_calls=10,
    window=60,
    error_detail="Too many authentication attempts — please wait a minute.",
))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


async def get_current_user(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> dict:
    """Dependency: decode JWT and return user dict {id, email}."""
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return {"id": payload["sub"], "email": payload["email"]}


async def _get_user_by_email(conn, email: str):
    return await conn.fetchrow(
        "SELECT id, email, name, password_hash, email_verified, avatar_url, created_at "
        "FROM users WHERE email=$1",
        email,
    )


async def _get_user_by_id(conn, user_id: str):
    return await conn.fetchrow(
        "SELECT id, email, name, password_hash, email_verified, avatar_url, created_at "
        "FROM users WHERE id=$1",
        uuid.UUID(user_id),
    )


async def _create_session(conn, user_id: str, remember: bool, ip: str, ua: str) -> str:
    refresh_token = make_refresh_token()
    days = REFRESH_EXPIRE_DAYS_REMEMBER if remember else REFRESH_EXPIRE_DAYS_SESSION
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    await conn.execute(
        """INSERT INTO user_sessions (id, user_id, refresh_token, ip_address, user_agent, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid.uuid4(),
        uuid.UUID(user_id),
        refresh_token,
        ip,
        ua,
        expires_at,
    )
    return refresh_token


def _user_response(user) -> dict:
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "email_verified": user["email_verified"],
        "avatar_url": user["avatar_url"],
        "created_at": user["created_at"].isoformat() if user["created_at"] else None,
    }


# ── Models ────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        return v

    @field_validator("name")
    @classmethod
    def non_empty_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        return v


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("https://"):
            raise ValueError("avatar_url must be an https:// URL")
        if len(v) > 512:
            raise ValueError("avatar_url is too long")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        return v


class ResendVerificationRequest(BaseModel):
    email: EmailStr


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request, _rl: None = _auth_rl):
    user_id = uuid.uuid4()
    pw_hash = hash_password(body.password)
    ev_token = secrets.token_urlsafe(32)
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute(
                    """INSERT INTO users (id, email, name, password_hash, email_verified)
                       VALUES ($1, $2, $3, $4, false)""",
                    user_id, body.email, body.name, pw_hash,
                )
            except asyncpg.UniqueViolationError:
                raise HTTPException(409, "Email already registered")

            await conn.execute(
                """INSERT INTO email_verification_tokens (token, user_id, expires_at)
                   VALUES ($1, $2, $3)""",
                ev_token, user_id, expires,
            )

    await send_verification_email(body.email, ev_token)
    await write_audit(body.email, "register", ip_address=_client_ip(request))

    return {"message": "Account created. Check your email to verify your account."}


async def _finish_login(conn, user, *, remember: bool, ip: str, ua: str) -> dict:
    """Shared tail of the login flow — creates the session and builds the
    token response. Used by both the direct (no-MFA) and MFA-challenge paths
    so they return byte-identical response shapes."""
    refresh_token = await _create_session(conn, str(user["id"]), remember, ip, ua)
    access_token = make_access_token(str(user["id"]), user["email"])
    await write_audit(user["email"], "login", ip_address=ip)

    from app.core.auth import make_token as _make_sub_token
    sub_token = _make_sub_token(user["email"], trial=True, days_remaining=30)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "sub_token": sub_token,
        "user": _user_response(user),
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, _rl: None = _auth_rl):
    ua = request.headers.get("User-Agent", "")
    ip = _client_ip(request)
    async with get_pool().acquire() as conn:
        user = await _get_user_by_email(conn, body.email)
        if not user or not user["password_hash"]:
            raise HTTPException(401, "Invalid email or password")
        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, "Invalid email or password")

        mfa = await conn.fetchrow(
            "SELECT enabled FROM mfa_secrets WHERE user_id=$1", user["id"]
        )
        if mfa and mfa["enabled"]:
            challenge_token = secrets.token_urlsafe(32)
            await conn.execute(
                "INSERT INTO mfa_challenges (token, user_id, expires_at) "
                "VALUES ($1,$2,NOW() + INTERVAL '5 minutes')",
                challenge_token, user["id"],
            )
            return {"mfa_required": True, "challenge_token": challenge_token}

        return await _finish_login(conn, user, remember=body.remember, ip=ip, ua=ua)


class LoginMfaRequest(BaseModel):
    challenge_token: str
    code: str
    remember: bool = False


@router.post("/login/mfa")
async def login_mfa(body: LoginMfaRequest, request: Request, _rl: None = _auth_rl):
    """Complete a login that was paused for MFA by POST /login."""
    import pyotp

    ua = request.headers.get("User-Agent", "")
    ip = _client_ip(request)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            challenge = await conn.fetchrow(
                "SELECT * FROM mfa_challenges WHERE token=$1 FOR UPDATE",
                body.challenge_token,
            )
            if not challenge:
                raise HTTPException(401, "Invalid or already-used MFA challenge")
            if challenge["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
                await conn.execute("DELETE FROM mfa_challenges WHERE token=$1", body.challenge_token)
                raise HTTPException(401, "MFA challenge expired — log in again")

            mfa = await conn.fetchrow(
                "SELECT secret, backup_codes FROM mfa_secrets WHERE user_id=$1 AND enabled=true",
                challenge["user_id"],
            )
            if not mfa:
                raise HTTPException(401, "MFA is not enabled for this account")

            code = body.code.strip().replace(" ", "")
            valid = pyotp.TOTP(mfa["secret"]).verify(code, valid_window=1)
            if not valid and code.upper() in (mfa["backup_codes"] or []):
                valid = True
                await conn.execute(
                    "UPDATE mfa_secrets SET backup_codes=array_remove(backup_codes,$2), updated_at=NOW() "
                    "WHERE user_id=$1",
                    challenge["user_id"], code.upper(),
                )
            if not valid:
                raise HTTPException(401, "Invalid authentication code")

            # One-time challenge — consume it now that it verified.
            await conn.execute("DELETE FROM mfa_challenges WHERE token=$1", body.challenge_token)
            user = await _get_user_by_id(conn, str(challenge["user_id"]))

        return await _finish_login(conn, user, remember=body.remember, ip=ip, ua=ua)


@router.post("/refresh")
async def refresh_token(body: RefreshRequest, _rl: None = _auth_rl):
    async with get_pool().acquire() as conn:
        session = await conn.fetchrow(
            """SELECT s.id, s.user_id, s.expires_at, u.email, u.name, u.email_verified, u.avatar_url, u.created_at
               FROM user_sessions s JOIN users u ON u.id=s.user_id
               WHERE s.refresh_token=$1""",
            body.refresh_token,
        )
        if not session:
            raise HTTPException(401, "Invalid refresh token")
        if session["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
            await conn.execute("DELETE FROM user_sessions WHERE id=$1", session["id"])
            raise HTTPException(401, "Session expired")

        # Rotate refresh token
        new_refresh = make_refresh_token()
        await conn.execute(
            "UPDATE user_sessions SET refresh_token=$1, last_used_at=NOW() WHERE id=$2",
            new_refresh,
            session["id"],
        )

    access_token = make_access_token(str(session["user_id"]), session["email"])
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(body: RefreshRequest):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM user_sessions WHERE refresh_token=$1", body.refresh_token
        )
    return {"message": "Logged out"}


@router.post("/logout-all")
async def logout_all(current: Annotated[dict, Depends(get_current_user)]):
    async with get_pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM user_sessions WHERE user_id=$1", uuid.UUID(current["id"])
        )
    return {"message": "All sessions terminated"}


@router.get("/verify-email/{token}")
async def verify_email(token: str):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, expires_at FROM email_verification_tokens WHERE token=$1", token
        )
        if not row:
            raise HTTPException(400, "Invalid or already-used verification link")
        if row["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
            await conn.execute(
                "DELETE FROM email_verification_tokens WHERE token=$1", token
            )
            raise HTTPException(400, "Verification link expired")

        await conn.execute(
            "UPDATE users SET email_verified=true WHERE id=$1", row["user_id"]
        )
        await conn.execute(
            "DELETE FROM email_verification_tokens WHERE token=$1", token
        )

    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
async def resend_verification(body: ResendVerificationRequest, _rl: None = _auth_rl):
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, email_verified FROM users WHERE email=$1", body.email
        )
        if not user or user["email_verified"]:
            # Don't reveal whether email exists
            return {"message": "If your email is registered and unverified, a new link has been sent"}

        # Delete old tokens, create new one
        await conn.execute(
            "DELETE FROM email_verification_tokens WHERE user_id=$1", user["id"]
        )
        ev_token = secrets.token_urlsafe(32)
        await conn.execute(
            """INSERT INTO email_verification_tokens (token, user_id, expires_at)
               VALUES ($1, $2, $3)""",
            ev_token,
            user["id"],
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        )

    await send_verification_email(body.email, ev_token)
    return {"message": "If your email is registered and unverified, a new link has been sent"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, _rl: None = _auth_rl):
    async with get_pool().acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM users WHERE email=$1", body.email)
        if not user:
            return {"message": "If that email is registered, a reset link has been sent"}

        # Delete old reset tokens
        await conn.execute(
            "DELETE FROM password_reset_tokens WHERE user_id=$1", user["id"]
        )
        reset_token = secrets.token_urlsafe(32)
        await conn.execute(
            """INSERT INTO password_reset_tokens (token, user_id, expires_at)
               VALUES ($1, $2, $3)""",
            reset_token,
            user["id"],
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        )

    await send_password_reset_email(body.email, reset_token)
    return {"message": "If that email is registered, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, _rl: None = _auth_rl):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, expires_at FROM password_reset_tokens WHERE token=$1", body.token
        )
        if not row:
            raise HTTPException(400, "Invalid or expired reset link")
        if row["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
            await conn.execute(
                "DELETE FROM password_reset_tokens WHERE token=$1", body.token
            )
            raise HTTPException(400, "Reset link expired")

        pw_hash = hash_password(body.password)
        await conn.execute(
            "UPDATE users SET password_hash=$1 WHERE id=$2", pw_hash, row["user_id"]
        )
        await conn.execute(
            "DELETE FROM password_reset_tokens WHERE token=$1", body.token
        )
        # Invalidate all sessions on password reset
        await conn.execute(
            "DELETE FROM user_sessions WHERE user_id=$1", row["user_id"]
        )

    return {"message": "Password reset successfully. Please log in with your new password."}


@router.get("/me")
async def get_me(current: Annotated[dict, Depends(get_current_user)]):
    async with get_pool().acquire() as conn:
        user = await _get_user_by_id(conn, current["id"])
        if not user:
            raise HTTPException(404, "User not found")
        return _user_response(user)


@router.put("/me")
async def update_me(
    body: UpdateProfileRequest,
    current: Annotated[dict, Depends(get_current_user)],
):
    # Explicit column allowlist — never interpolate untrusted strings into SQL
    _ALLOWED = {"name", "avatar_url"}

    updates: dict[str, str] = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.avatar_url is not None:
        updates["avatar_url"] = body.avatar_url

    if not updates:
        raise HTTPException(400, "No fields to update")

    # Verify every key is in the allowlist (guards against future misuse)
    if not updates.keys() <= _ALLOWED:
        raise HTTPException(400, "Invalid field")

    # Build parameterised SET clause using only known-safe column names
    parts = [f"{col}=${i + 2}" for i, col in enumerate(updates)]
    set_clause = ", ".join(parts)

    async with get_pool().acquire() as conn:
        user = await conn.fetchrow(
            f"UPDATE users SET {set_clause} WHERE id=$1"  # noqa: S608 — keys validated above
            " RETURNING id, email, name, email_verified, avatar_url, created_at",
            uuid.UUID(current["id"]),
            *updates.values(),
        )
        if not user:
            raise HTTPException(404, "User not found")
        return _user_response(user)


@router.put("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current: Annotated[dict, Depends(get_current_user)],
):
    async with get_pool().acquire() as conn:
        user = await _get_user_by_id(conn, current["id"])
        if not user or not user["password_hash"]:
            raise HTTPException(400, "Cannot change password")
        if not verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(400, "Current password is incorrect")
        await conn.execute(
            "UPDATE users SET password_hash=$1 WHERE id=$2",
            hash_password(body.new_password),
            uuid.UUID(current["id"]),
        )
    return {"message": "Password changed successfully"}


# ── MFA / TOTP ──────────────────────────────────────────────────────────────

class MfaEnableRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    password: str


def _generate_backup_codes(n: int = 10) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(n)]


@router.post("/mfa/setup")
async def mfa_setup(current: Annotated[dict, Depends(get_current_user)]):
    """Generate (or regenerate) a TOTP secret. Not active until /mfa/enable
    verifies one code — a user can safely re-run this if they lose the QR."""
    import pyotp

    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=current["email"], issuer_name="Axon")
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO mfa_secrets (user_id, secret, enabled, backup_codes)
               VALUES ($1,$2,false,'{}')
               ON CONFLICT (user_id) DO UPDATE
               SET secret=EXCLUDED.secret, enabled=false, updated_at=NOW()""",
            uuid.UUID(current["id"]), secret,
        )
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/mfa/enable")
async def mfa_enable(body: MfaEnableRequest, current: Annotated[dict, Depends(get_current_user)]):
    """Verify one TOTP code to activate MFA; returns one-time backup codes."""
    import pyotp

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT secret FROM mfa_secrets WHERE user_id=$1", uuid.UUID(current["id"]),
        )
        if not row:
            raise HTTPException(400, "Call /mfa/setup first")
        if not pyotp.TOTP(row["secret"]).verify(body.code.strip(), valid_window=1):
            raise HTTPException(400, "Invalid authentication code")

        backup_codes = _generate_backup_codes()
        await conn.execute(
            "UPDATE mfa_secrets SET enabled=true, backup_codes=$2, updated_at=NOW() WHERE user_id=$1",
            uuid.UUID(current["id"]), backup_codes,
        )
    await write_audit(current["email"], "mfa.enabled")
    return {"enabled": True, "backup_codes": backup_codes}


@router.post("/mfa/disable")
async def mfa_disable(body: MfaDisableRequest, current: Annotated[dict, Depends(get_current_user)]):
    async with get_pool().acquire() as conn:
        user = await _get_user_by_id(conn, current["id"])
        if not user or not user["password_hash"] or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(400, "Incorrect password")
        await conn.execute("DELETE FROM mfa_secrets WHERE user_id=$1", uuid.UUID(current["id"]))
    await write_audit(current["email"], "mfa.disabled")
    return {"enabled": False}


@router.post("/mfa/backup-codes")
async def mfa_regenerate_backup_codes(current: Annotated[dict, Depends(get_current_user)]):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT enabled FROM mfa_secrets WHERE user_id=$1", uuid.UUID(current["id"]),
        )
        if not row or not row["enabled"]:
            raise HTTPException(400, "MFA is not enabled")
        backup_codes = _generate_backup_codes()
        await conn.execute(
            "UPDATE mfa_secrets SET backup_codes=$2, updated_at=NOW() WHERE user_id=$1",
            uuid.UUID(current["id"]), backup_codes,
        )
    return {"backup_codes": backup_codes}


@router.get("/sessions")
async def list_sessions(current: Annotated[dict, Depends(get_current_user)]):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, ip_address, user_agent, created_at, last_used_at, expires_at
               FROM user_sessions WHERE user_id=$1 ORDER BY last_used_at DESC NULLS LAST""",
            uuid.UUID(current["id"]),
        )
    return [
        {
            "id": str(r["id"]),
            "ip_address": r["ip_address"],
            "user_agent": r["user_agent"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
        }
        for r in rows
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current: Annotated[dict, Depends(get_current_user)],
):
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_sessions WHERE id=$1 AND user_id=$2",
            uuid.UUID(session_id),
            uuid.UUID(current["id"]),
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Session not found")
    return {"message": "Session revoked"}


@router.delete("/me")
async def delete_account(
    body: LoginRequest,
    current: Annotated[dict, Depends(get_current_user)],
    request: Request,
):
    """Permanently delete account. Requires password confirmation."""
    if body.email != current["email"]:
        raise HTTPException(400, "Email does not match")
    async with get_pool().acquire() as conn:
        user = await _get_user_by_id(conn, current["id"])
        # password_hash can be NULL for OAuth-created accounts; treat as invalid credentials
        if not user or not user["password_hash"]:
            raise HTTPException(400, "Invalid credentials")
        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(400, "Invalid credentials")
        await conn.execute("DELETE FROM users WHERE id=$1", uuid.UUID(current["id"]))

    await write_audit(current["email"], "account_deleted", ip_address=_client_ip(request))
    return {"message": "Account deleted"}


# ── OAuth (Google + GitHub + Microsoft) ────────────────────────────────────────

import os as _os
import httpx as _httpx
from fastapi.responses import RedirectResponse

_GOOGLE_CLIENT_ID        = _os.getenv("GOOGLE_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET    = _os.getenv("GOOGLE_CLIENT_SECRET", "")
_GITHUB_CLIENT_ID        = _os.getenv("GITHUB_CLIENT_ID", "")
_GITHUB_CLIENT_SECRET    = _os.getenv("GITHUB_CLIENT_SECRET", "")
_MICROSOFT_CLIENT_ID     = _os.getenv("MICROSOFT_CLIENT_ID", "")
_MICROSOFT_CLIENT_SECRET = _os.getenv("MICROSOFT_CLIENT_SECRET", "")
_APP_URL_BASE            = _os.getenv("APP_URL", "http://localhost:8000")


def _oauth_not_configured(provider: str):
    raise HTTPException(503, f"{provider} OAuth is not configured on this server. "
                             f"Set {provider.upper()}_CLIENT_ID and {provider.upper()}_CLIENT_SECRET.")


async def _upsert_oauth_user(conn, email: str, name: str, avatar_url: str, provider: str):
    """Create or update a user from OAuth; return the user row."""
    existing = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
    if existing:
        await conn.execute(
            "UPDATE users SET name=COALESCE($2, name), avatar_url=COALESCE($3, avatar_url), "
            "email_verified=true WHERE id=$1",
            existing["id"], name or None, avatar_url or None,
        )
        return existing
    new_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO users (id, email, name, avatar_url, email_verified, password_hash, created_at)
           VALUES ($1,$2,$3,$4,true,NULL,NOW())""",
        new_id, email, name or email.split("@")[0], avatar_url or None,
    )
    return await conn.fetchrow("SELECT * FROM users WHERE id=$1", new_id)


async def _make_oauth_session(conn, user, ip: str, ua: str) -> dict:
    """Build an OAuth login session AND persist its refresh token to
    user_sessions — the same table/shape _create_session() uses for
    password login, so /api/auth/refresh, /sessions, and logout-all work
    identically regardless of how the user signed in."""
    from app.core.auth import make_token as _make_sub_token
    access  = make_access_token(str(user["id"]), user["email"])
    refresh = make_refresh_token()
    sub_tok = _make_sub_token(user["email"], trial=True, days_remaining=30)
    await conn.execute(
        """INSERT INTO user_sessions (id, user_id, refresh_token, ip_address, user_agent, expires_at)
           VALUES ($1, $2, $3, $4, $5, NOW() + INTERVAL '30 days')""",
        uuid.uuid4(), user["id"], refresh, ip, ua,
    )
    return {"access_token": access, "refresh_token": refresh, "sub_token": sub_tok}


@router.get("/google")
async def google_oauth_start():
    if not _GOOGLE_CLIENT_ID:
        _oauth_not_configured("Google")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/google/callback"
    params = (
        f"client_id={_GOOGLE_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_oauth_callback(code: str, request: Request):
    if not _GOOGLE_CLIENT_ID:
        _oauth_not_configured("Google")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/google/callback"
    async with _httpx.AsyncClient() as client:
        token_res = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": _GOOGLE_CLIENT_ID,
            "client_secret": _GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            raise HTTPException(400, "Google OAuth token exchange failed")
        tokens = token_res.json()
        info_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if info_res.status_code != 200:
            raise HTTPException(400, "Failed to fetch Google user info")
        info = info_res.json()

    email = info.get("email")
    if not email:
        raise HTTPException(400, "Google did not return an email address")

    async with get_pool().acquire() as conn:
        user = await _upsert_oauth_user(conn, email, info.get("name", ""), info.get("picture", ""), "google")
        session = await _make_oauth_session(conn, user, _client_ip(request), request.headers.get("User-Agent", ""))

    # Redirect to frontend with tokens in query params (picked up by AuthPage)
    p = (f"access_token={session['access_token']}"
         f"&refresh_token={session['refresh_token']}"
         f"&sub_token={session['sub_token']}")
    return RedirectResponse(f"{_APP_URL_BASE}/oauth-callback?{p}")


@router.get("/microsoft")
async def microsoft_oauth_start():
    if not _MICROSOFT_CLIENT_ID:
        _oauth_not_configured("Microsoft")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/microsoft/callback"
    params = (
        f"client_id={_MICROSOFT_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&response_mode=query"
        f"&scope=openid%20email%20profile"
    )
    return RedirectResponse(f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{params}")


@router.get("/microsoft/callback")
async def microsoft_oauth_callback(code: str, request: Request):
    if not _MICROSOFT_CLIENT_ID:
        _oauth_not_configured("Microsoft")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/microsoft/callback"
    async with _httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "code": code, "client_id": _MICROSOFT_CLIENT_ID,
                "client_secret": _MICROSOFT_CLIENT_SECRET,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
        )
        if token_res.status_code != 200:
            raise HTTPException(400, "Microsoft OAuth token exchange failed")
        tokens = token_res.json()
        info_res = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if info_res.status_code != 200:
            raise HTTPException(400, "Failed to fetch Microsoft user info")
        info = info_res.json()

    email = info.get("mail") or info.get("userPrincipalName")
    if not email:
        raise HTTPException(400, "Microsoft did not return an email address")

    async with get_pool().acquire() as conn:
        user = await _upsert_oauth_user(conn, email, info.get("displayName", ""), "", "microsoft")
        session = await _make_oauth_session(conn, user, _client_ip(request), request.headers.get("User-Agent", ""))

    p = (f"access_token={session['access_token']}"
         f"&refresh_token={session['refresh_token']}"
         f"&sub_token={session['sub_token']}")
    return RedirectResponse(f"{_APP_URL_BASE}/oauth-callback?{p}")


@router.get("/github")
async def github_oauth_start():
    if not _GITHUB_CLIENT_ID:
        _oauth_not_configured("GitHub")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/github/callback"
    params = (
        f"client_id={_GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=user:email"
    )
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@router.get("/github/callback")
async def github_oauth_callback(code: str, request: Request):
    if not _GITHUB_CLIENT_ID:
        _oauth_not_configured("GitHub")
    redirect_uri = f"{_APP_URL_BASE}/api/auth/github/callback"
    async with _httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": _GITHUB_CLIENT_ID, "client_secret": _GITHUB_CLIENT_SECRET,
                  "code": code, "redirect_uri": redirect_uri},
        )
        if token_res.status_code != 200:
            raise HTTPException(400, "GitHub OAuth token exchange failed")
        gh_access = token_res.json().get("access_token")
        if not gh_access:
            raise HTTPException(400, "GitHub did not return an access token")

        user_res = await client.get("https://api.github.com/user",
                                    headers={"Authorization": f"Bearer {gh_access}"})
        emails_res = await client.get("https://api.github.com/user/emails",
                                      headers={"Authorization": f"Bearer {gh_access}"})
        if user_res.status_code != 200:
            raise HTTPException(400, "Failed to fetch GitHub user info")
        gh_user = user_res.json()
        emails = emails_res.json() if emails_res.status_code == 200 else []

    # Pick primary verified email
    email = gh_user.get("email")
    if not email and emails:
        primary = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
        email = primary or emails[0].get("email")
    if not email:
        raise HTTPException(400, "GitHub account has no public email. Add a public email to your GitHub profile.")

    async with get_pool().acquire() as conn:
        avatar = gh_user.get("avatar_url", "")
        user = await _upsert_oauth_user(conn, email, gh_user.get("name") or gh_user.get("login", ""), avatar, "github")
        session = await _make_oauth_session(conn, user, _client_ip(request), request.headers.get("User-Agent", ""))

    p = (f"access_token={session['access_token']}"
         f"&refresh_token={session['refresh_token']}"
         f"&sub_token={session['sub_token']}")
    return RedirectResponse(f"{_APP_URL_BASE}/oauth-callback?{p}")
