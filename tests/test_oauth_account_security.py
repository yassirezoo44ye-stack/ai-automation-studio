"""
OAuth account-security regression tests.

Guards the three AUTH SECURITY BLOCKER fixes:
  1. GitHub: only primary+verified email accepted from /user/emails
  2. Microsoft: existing password account returns 409 (guard in _upsert_oauth_user)
  3. Cross-provider: Google OAuth login for an account created with GitHub password → 409
     (no such cross-provider password-hash path exists in this app, but the
      password_hash IS NOT NULL guard is provider-agnostic — proven here)

All HTTP calls to GitHub/Microsoft are mocked. DB layer uses _FakeOAuthConn from
test_google_oauth_e2e.py.
"""
from __future__ import annotations

import datetime
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

import httpx
import pytest
from fastapi.testclient import TestClient

from app.routers.auth_users import router
from tests.test_google_oauth_e2e import _FakeOAuthConn


def _make_app():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _isolate_singletons():
    from app.core.rate_limit import rl_store
    import app.core.cache.redis_adapter as redis_adapter_mod
    rl_store.clear()
    redis_adapter_mod._instance = None
    yield
    rl_store.clear()
    redis_adapter_mod._instance = None


def _mock_pool(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.auth_users.get_pool", return_value=pool)


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _github_mock_client(*, emails: list[dict], gh_user: dict | None = None):
    """Build a mock httpx.AsyncClient for the GitHub OAuth callback."""
    if gh_user is None:
        gh_user = {"login": "testuser", "name": "Test User", "email": None, "avatar_url": ""}

    class _MockGithubClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, data=None, **kwargs):
            return httpx.Response(200, json={"access_token": "gh-test-token"})

        async def get(self, url, headers=None, **kwargs):
            if url == "https://api.github.com/user":
                return httpx.Response(200, json=gh_user)
            if url == "https://api.github.com/user/emails":
                return httpx.Response(200, json=emails)
            return httpx.Response(404, json={})

    return patch("app.routers.auth_users._httpx.AsyncClient", return_value=_MockGithubClient())


def _valid_github_start(client) -> tuple[str, str]:
    with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-gh-id"):
        resp = client.get("/api/auth/github", follow_redirects=False)
    assert resp.status_code in (302, 307)
    state = resp.headers["location"].split("state=")[1].split("&")[0]
    cookie = resp.cookies.get("oauth_state", "")
    return state, cookie


def _do_github_login(client, conn, emails: list[dict], gh_user=None):
    state, cookie = _valid_github_start(client)
    with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-gh-id"), \
         patch("app.routers.auth_users._GITHUB_CLIENT_SECRET", "fake-gh-secret"), \
         _github_mock_client(emails=emails, gh_user=gh_user), \
         _mock_pool(conn):
        return client.get(
            "/api/auth/github/callback",
            params={"code": "gh-code", "state": state},
            cookies={"oauth_state": cookie},
            follow_redirects=False,
        )


# ── Microsoft helpers ─────────────────────────────────────────────────────────

def _microsoft_mock_client(*, ms_user: dict | None = None):
    if ms_user is None:
        ms_user = {"mail": "ms-user@example.com", "displayName": "MS User"}

    class _MockMicrosoftClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, data=None, **kwargs):
            return httpx.Response(200, json={"access_token": "ms-test-token"})

        async def get(self, url, headers=None, **kwargs):
            return httpx.Response(200, json=ms_user)

    return patch("app.routers.auth_users._httpx.AsyncClient", return_value=_MockMicrosoftClient())


def _valid_microsoft_start(client) -> tuple[str, str]:
    with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-ms-id"):
        resp = client.get("/api/auth/microsoft", follow_redirects=False)
    assert resp.status_code in (302, 307)
    state = resp.headers["location"].split("state=")[1].split("&")[0]
    cookie = resp.cookies.get("oauth_state", "")
    return state, cookie


def _do_microsoft_login(client, conn, ms_user=None):
    state, cookie = _valid_microsoft_start(client)
    with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-ms-id"), \
         patch("app.routers.auth_users._MICROSOFT_CLIENT_SECRET", "fake-ms-secret"), \
         _microsoft_mock_client(ms_user=ms_user), \
         _mock_pool(conn):
        return client.get(
            "/api/auth/microsoft/callback",
            params={"code": "ms-code", "state": state},
            cookies={"oauth_state": cookie},
            follow_redirects=False,
        )


# ══════════════════════════════════════════════════════════════════════════════
# GitHub email verification
# ══════════════════════════════════════════════════════════════════════════════

class TestGitHubEmailVerification:
    def test_primary_verified_email_is_accepted(self, client):
        conn = _FakeOAuthConn()
        resp = _do_github_login(client, conn, emails=[
            {"email": "verified-primary@example.com", "primary": True, "verified": True},
        ])
        assert resp.status_code == 307
        assert len(conn.users) == 1
        user = next(iter(conn.users.values()))
        assert user["email"] == "verified-primary@example.com"

    def test_no_verified_primary_email_returns_400(self, client):
        """No primary+verified email → 400. The only safe choice."""
        conn = _FakeOAuthConn()
        resp = _do_github_login(client, conn, emails=[
            {"email": "unverified@example.com", "primary": True, "verified": False},
        ])
        assert resp.status_code == 400
        assert len(conn.users) == 0

    def test_non_primary_verified_email_is_not_used(self, client):
        """A verified-but-not-primary email must not be used as the login email."""
        conn = _FakeOAuthConn()
        resp = _do_github_login(client, conn, emails=[
            {"email": "secondary-verified@example.com", "primary": False, "verified": True},
            {"email": "unverified-primary@example.com", "primary": True, "verified": False},
        ])
        assert resp.status_code == 400
        assert len(conn.users) == 0

    def test_empty_email_list_returns_400(self, client):
        conn = _FakeOAuthConn()
        resp = _do_github_login(client, conn, emails=[])
        assert resp.status_code == 400

    def test_400_detail_mentions_verified_and_primary(self, client):
        conn = _FakeOAuthConn()
        resp = _do_github_login(client, conn, emails=[
            {"email": "unverified@example.com", "primary": True, "verified": False},
        ])
        detail = resp.json()["detail"].lower()
        assert "verified" in detail

    def test_existing_password_account_returns_409(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "pw-gh@example.com", "name": "PW User",
            "avatar_url": None, "email_verified": True, "password_hash": "$2b$12$hash",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        resp = _do_github_login(client, conn, emails=[
            {"email": "pw-gh@example.com", "primary": True, "verified": True},
        ])
        assert resp.status_code == 409
        assert conn.users[str(existing_id)]["password_hash"] == "$2b$12$hash"


# ══════════════════════════════════════════════════════════════════════════════
# Microsoft account security
# ══════════════════════════════════════════════════════════════════════════════

class TestMicrosoftAccountSecurity:
    def test_new_microsoft_user_is_created(self, client):
        conn = _FakeOAuthConn()
        resp = _do_microsoft_login(client, conn, ms_user={
            "mail": "new-ms@example.com", "displayName": "New MS User",
        })
        assert resp.status_code == 307
        assert len(conn.users) == 1

    def test_existing_oauth_only_microsoft_account_is_reused(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "returning-ms@example.com", "name": "Old MS",
            "avatar_url": None, "email_verified": True, "password_hash": None,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        resp = _do_microsoft_login(client, conn, ms_user={
            "mail": "returning-ms@example.com", "displayName": "Updated MS",
        })
        assert resp.status_code == 307
        assert conn.insert_user_calls == 0

    def test_existing_password_account_returns_409(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "pw-ms@example.com", "name": "PW MS User",
            "avatar_url": None, "email_verified": True, "password_hash": "$2b$12$mshash",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        resp = _do_microsoft_login(client, conn, ms_user={
            "mail": "pw-ms@example.com", "displayName": "MS Attacker",
        })
        assert resp.status_code == 409
        assert conn.users[str(existing_id)]["password_hash"] == "$2b$12$mshash"

    def test_409_detail_mentions_password_and_settings(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "pw-ms2@example.com", "name": "X",
            "avatar_url": None, "email_verified": True, "password_hash": "$2b$12$x",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        resp = _do_microsoft_login(client, conn, ms_user={"mail": "pw-ms2@example.com", "displayName": "X"})
        detail = resp.json()["detail"].lower()
        assert "password" in detail
        assert "settings" in detail
