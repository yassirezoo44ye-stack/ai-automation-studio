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
from typing import Optional

from fastapi import Request

from app.core.config import SESSION_SECRET, TOKEN_TTL


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


def owner_email(request: Request) -> str:
    """The per-user identity used to scope owned records (tasks, etc.).

    Derived from the same subscription token the auth middleware already
    validated, so no extra DB round-trip is needed.
    """
    token = (
        request.headers.get("X-Sub-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("sub_token", "")
    )
    payload = verify_token(token) if token else None
    return payload["e"] if payload else "demo@local"
