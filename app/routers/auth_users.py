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


@router.post("/login")
async def login(body: LoginRequest, request: Request, _rl: None = _auth_rl):
    async with get_pool().acquire() as conn:
        user = await _get_user_by_email(conn, body.email)
        if not user or not user["password_hash"]:
            raise HTTPException(401, "Invalid email or password")
        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, "Invalid email or password")

        ua = request.headers.get("User-Agent", "")
        ip = _client_ip(request)
        refresh_token = await _create_session(conn, str(user["id"]), body.remember, ip, ua)

    access_token = make_access_token(str(user["id"]), user["email"])
    await write_audit(body.email, "login", ip_address=ip)

    from app.core.auth import make_token as _make_sub_token
    sub_token = _make_sub_token(user["email"], trial=True, days_remaining=30)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "sub_token": sub_token,
        "user": _user_response(user),
    }


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
