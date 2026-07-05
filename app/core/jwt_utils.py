"""JWT access tokens + opaque refresh tokens."""
import datetime
import secrets

import jwt

from app.core.config import SESSION_SECRET as _SECRET

_ALGO = "HS256"
ACCESS_EXPIRE_MINUTES = 15
REFRESH_EXPIRE_DAYS_REMEMBER = 30
REFRESH_EXPIRE_DAYS_SESSION = 1


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
    """Raise jwt.PyJWTError if invalid or expired."""
    return jwt.decode(token, _SECRET, algorithms=[_ALGO])


def make_refresh_token() -> str:
    return secrets.token_urlsafe(48)
