"""Password hashing, JWT access tokens, opaque refresh tokens, CSRF tokens.

Design:
- Passwords: Argon2id via passlib. Never logged, never returned.
- Access token: short-lived JWT (HS256), carries `sub` (user id), `email`, `type=access`,
  `iat`, `exp`, `jti`. Sent as a Bearer header, kept in memory on the client — never
  written to a cookie, so it is immune to cookie-based CSRF.
- Refresh token: a high-entropy opaque random string. Only its SHA-256 hash is stored
  in the database (so a DB read alone cannot be replayed as a live token). Delivered to
  the client exclusively via an httpOnly, Secure, SameSite=Strict cookie. Rotated
  (old row revoked, new row inserted) on every use — see services/auth_service.py.
- CSRF token: a random value mirrored into a non-httpOnly cookie and required as a
  header on cookie-authenticated, state-changing requests (double-submit pattern).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

REFRESH_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #

def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except ValueError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _pwd_context.needs_update(password_hash)


# --------------------------------------------------------------------------- #
# Access tokens (JWT)
# --------------------------------------------------------------------------- #

class TokenError(Exception):
    """Raised for any invalid/expired/malformed token."""


def create_access_token(*, user_id: uuid.UUID, email: str, extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid access token") from exc
    if payload.get("type") != "access":
        raise TokenError("Wrong token type")
    return payload


# --------------------------------------------------------------------------- #
# Refresh tokens (opaque, DB-backed)
# --------------------------------------------------------------------------- #

def generate_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token_for_cookie, sha256_hash_for_db, expires_at)."""
    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    token_hash = hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
    return raw, token_hash, expires_at


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# CSRF (double-submit)
# --------------------------------------------------------------------------- #

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def csrf_tokens_match(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)
