"""
Subscription-token authentication.

Tokens are HMAC-SHA256–signed, base64url-encoded JSON blobs — no external
JWT library needed.  They carry the subscriber's email, expiry, and trial
status so the backend can derive per-user identity without a DB lookup on
every request.
"""
import base64
import hashlib
import hmac
import json
import time as _time
import uuid
from typing import Optional

from fastapi import HTTPException, Request

from app.core.config import SESSION_SECRET, TOKEN_TTL


def derive_fernet_key(namespace: str = "") -> bytes:
    """Deterministically derive a 32-byte urlsafe-base64 Fernet key from
    SESSION_SECRET — no separate key-management step needed. `namespace`
    keeps different subsystems' derived keys distinct (e.g. plugin secrets
    vs. integration credentials) without a second secret to manage.

    Shared by app/plugins/secrets.py and app/integrations/credential_store.py
    — both encrypt at rest with Fernet keyed this way; each still keeps its
    own @lru_cache(maxsize=1)-wrapped Fernet() instance, this just factors
    out the derivation math they'd otherwise duplicate."""
    material = f"{SESSION_SECRET}:{namespace}" if namespace else SESSION_SECRET
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def make_token(email: str, trial: bool, days_remaining: int) -> str:
    payload = {
        "e":     email,
        "exp":   int(_time.time()) + TOKEN_TTL,
        "trial": trial,
        "dr":    days_remaining,
    }
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig  = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        data, sig = token.rsplit(".", 1)
        expected  = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded  = data + "=" * (4 - len(data) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["exp"] < int(_time.time()):
            return None
        return payload
    except Exception:
        return None


def extract_auth_credentials(request: Request) -> tuple[str, str]:
    """(sub_token, bearer) from a request — the dual-auth extraction shared
    by owner_email() below and factory.py's api_auth_middleware. sub_token
    comes from X-Sub-Token or the sub_token cookie; bearer is the
    Authorization header with any "Bearer " prefix stripped."""
    sub_token = (
        request.headers.get("X-Sub-Token")
        or request.cookies.get("sub_token", "")
    )
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return sub_token, bearer


def owner_email(request: Request) -> str:
    """The per-user identity used to scope owned records (tasks, etc.).

    Tries subscription token first; falls back to JWT so that users who
    authenticated via the new JWT auth system are identified correctly.
    """
    sub_token, bearer = extract_auth_credentials(request)
    payload = verify_token(sub_token) if sub_token else None
    if not payload and bearer:
        # A subscription token is also accepted via Authorization: Bearer,
        # not just X-Sub-Token/cookie.
        payload = verify_token(bearer)
    if payload:
        return payload["e"]

    # Fall back to JWT
    if bearer:
        try:
            from app.core.jwt_utils import decode_access_token
            claims = decode_access_token(bearer)
            return claims.get("email", "demo@local")
        except Exception:
            pass
    return "demo@local"


async def owner_user_id(conn, request: Request) -> uuid.UUID:
    """Resolve the authenticated subscriber's users.id row via their token
    email. Shared by every endpoint that must scope a query to "my data
    only" (projects, stats, usage) — a single source of truth so scoping
    can't silently drift per-router."""
    email = owner_email(request)
    uid = await conn.fetchval("SELECT id FROM users WHERE email=$1", email)
    if not uid:
        raise HTTPException(401, "No account found for this subscription — please register.")
    return uid
