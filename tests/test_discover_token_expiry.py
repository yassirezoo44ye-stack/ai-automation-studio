"""Discover reports an expired access token as "Token expired".

A still-valid subscription token lets the request past the auth middleware;
Discover's likes/saves then failed with "Authentication required", which the
client doesn't refresh on.
"""
import datetime

import jwt
import pytest
from fastapi import HTTPException

from app.core import jwt_utils
from app.routers.discover import _require_user_id


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _token(delta: datetime.timedelta) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode({"sub": "user-1", "iat": now, "exp": now + delta}, jwt_utils._SECRET, algorithm=jwt_utils._ALGO)


def test_expired_access_token_reads_as_token_expired():
    with pytest.raises(HTTPException) as err:
        _require_user_id(_Req(_token(datetime.timedelta(minutes=-1))))
    assert (err.value.status_code, err.value.detail) == (401, "Token expired")


def test_missing_or_invalid_token_still_requires_authentication():
    for req in (_Req(), _Req("not-a-jwt")):
        with pytest.raises(HTTPException) as err:
            _require_user_id(req)
        assert err.value.detail == "Authentication required"


def test_valid_token_returns_user_id():
    assert _require_user_id(_Req(_token(datetime.timedelta(minutes=5)))) == "user-1"
