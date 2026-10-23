"""JWT access tokens + opaque refresh tokens."""
import datetime
import secrets
import time

import jwt

from app.core.config import SESSION_SECRET as _SECRET

_ALGO = "HS256"
ACCESS_EXPIRE_MINUTES = 5
REFRESH_EXPIRE_DAYS_REMEMBER = 30
REFRESH_EXPIRE_DAYS_SESSION = 1

# Per-user revocation timestamps.  Any access token whose iat ≤ the stored
# timestamp is treated as expired regardless of its own exp claim.  Entries
# are short-lived (TTL = ACCESS_EXPIRE_MINUTES + buffer) so memory is bounded.
_revoked_before: dict[str, float] = {}


async def revoke_user_tokens(user_id: str) -> None:
    """Revoke all outstanding access tokens for *user_id* immediately.

    Writes to the in-process store and, when Redis is available, to a
    shared key so multiple server instances honour the revocation.
    """
    now = time.time()
    _revoked_before[user_id] = now
    try:
        from app.core.cache import get_redis
        cache = await get_redis()
        await cache.set(
            f"jwt:revoke:{user_id}",
            str(now),
            ttl=ACCESS_EXPIRE_MINUTES * 60 + 30,
        )
    except Exception:
        pass


def make_access_token(user_id: str, email: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=ACCESS_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def decode_access_token(token: str) -> dict:
    """Raise jwt.PyJWTError if invalid, expired, or explicitly revoked."""
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGO], options={"verify_iat": False})
    user_id = payload.get("sub")
    iat = payload.get("iat")
    if user_id and iat is not None:
        iat_ts = iat.timestamp() if isinstance(iat, datetime.datetime) else float(iat)
        revoke_before = _revoked_before.get(user_id)
        if revoke_before and iat_ts <= revoke_before:
            raise jwt.ExpiredSignatureError("Token has been revoked")
    return payload


def make_refresh_token() -> str:
    return secrets.token_urlsafe(48)
