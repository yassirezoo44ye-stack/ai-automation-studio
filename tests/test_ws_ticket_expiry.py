"""POST /api/ws/ticket reports an expired access token as "Token expired".

That is the body apiFetch refreshes on. The endpoint used to answer
"Invalid or expired token", so live-update hooks retried the stale token
every ~30s (seen in production) instead of refreshing the session.
"""
import datetime

import jwt
import pytest
from fastapi import HTTPException

from app.core import jwt_utils
from app.routers.ws_ticket import _require_jwt_user_id


class _Req:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}


def _token(exp_delta: datetime.timedelta) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode({"sub": "user-1", "iat": now, "exp": now + exp_delta}, jwt_utils._SECRET, algorithm=jwt_utils._ALGO)


def test_expired_token_is_reported_as_token_expired():
    with pytest.raises(HTTPException) as err:
        _require_jwt_user_id(_Req(_token(datetime.timedelta(minutes=-5))))
    assert err.value.status_code == 401
    assert err.value.detail == "Token expired"


def test_tampered_token_is_still_invalid_not_expired():
    with pytest.raises(HTTPException) as err:
        _require_jwt_user_id(_Req(_token(datetime.timedelta(minutes=5)) + "x"))
    assert err.value.detail == "Invalid or expired token"


def test_valid_token_returns_user_id():
    assert _require_jwt_user_id(_Req(_token(datetime.timedelta(minutes=5)))) == "user-1"
