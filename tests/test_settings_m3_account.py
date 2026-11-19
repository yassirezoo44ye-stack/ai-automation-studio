"""
Settings audit, milestone 3: the Account & security tab needs /me to say
whether the account has a password and two-factor on, and profile names
must be non-blank.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.routers import auth_users

USER_ID = str(uuid.uuid4())


class _Conn:
    def __init__(self, mfa):
        self.mfa = mfa

    async def fetchrow(self, sql, *args):
        assert "mfa_secrets" in sql
        return None if self.mfa is None else {"enabled": self.mfa}


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def _user(password_hash):
    return {
        "id": uuid.UUID(USER_ID), "email": "u@example.com", "name": "U",
        "email_verified": True, "avatar_url": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "password_hash": password_hash,
    }


@pytest.mark.parametrize("pw_hash, mfa, has_pw, mfa_on", [
    ("$2b$hash", True, True, True),
    (None, None, False, False),
    ("$2b$hash", False, True, False),
])
async def test_me_reports_password_and_mfa(monkeypatch, pw_hash, mfa, has_pw, mfa_on):
    async def _get(conn, uid):
        return _user(pw_hash)
    monkeypatch.setattr(auth_users, "_get_user_by_id", _get)
    monkeypatch.setattr(auth_users, "get_pool", lambda: _Pool(_Conn(mfa)))
    out = await auth_users.get_me({"id": USER_ID, "email": "u@example.com"})
    assert out["has_password"] is has_pw
    assert out["mfa_enabled"] is mfa_on
    assert "password_hash" not in out


def test_profile_name_is_trimmed_and_bounded():
    assert auth_users.UpdateProfileRequest(name="  Sam  ").name == "Sam"
    assert auth_users.UpdateProfileRequest().name is None
    for bad in ("   ", "x" * 101):
        with pytest.raises(ValidationError):
            auth_users.UpdateProfileRequest(name=bad)
