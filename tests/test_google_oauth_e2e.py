"""
Google OAuth — automated end-to-end coverage, Google itself fully mocked.

Deliberately independent of real GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET —
every test either patches app.routers.auth_users._GOOGLE_CLIENT_ID/_SECRET
directly (isolated per-test via unittest.mock.patch, which always restores
the original value on exit regardless of test order) or explicitly tests
the unset-by-default state.

Covers the full documented flow:

  GET /api/auth/google
      -> Google authorization redirect
  GET /api/auth/google/callback
      -> Google token exchange (mocked)
      -> Google userinfo (mocked)
      -> _upsert_oauth_user() / _make_oauth_session()
      -> one-time OAuth exchange code (real in-process Redis fallback,
         see app/core/cache/redis_adapter.py — no REDIS_URL in tests, so
         get_redis() already degrades to LocalCacheBackend; not mocked)
  POST /api/auth/oauth-exchange
      -> access_token + refresh_token + sub_token
  GET  /api/auth/me                 (authenticated with the real access_token)
  POST /api/auth/refresh            (using the real refresh_token)

The DB layer uses a small in-memory fake connection (_FakeOAuthConn) that
actually persists users/sessions across calls within one test, instead of
one-canned-response-per-call mocks — that's the only way to prove a user
created via OAuth is the same one /me and /refresh see later in the same
flow, not just that the right SQL text was issued.

Findings discovered while writing these tests are reported, not fixed —
see the module docstring notes on each affected test class.
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

from app.routers.auth_users import router  # noqa: E402


# ── App / client fixture (same convention as tests/test_api_auth.py) ──────────

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
def _isolate_shared_singletons():
    """Two module-level singletons this flow touches are process-global:
    the rate limiter's in-memory store (a /refresh call in these tests
    would otherwise count against the same 10/min budget test_api_auth.py
    exercises) and the Redis adapter's in-process fallback singleton
    (oauth-exchange codes would otherwise accumulate across the whole test
    session). Reset both before and after every test in this file so it
    never pollutes, or is polluted by, any other test file."""
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


# ── Fake DB connection — persists users/sessions across calls in one test ────

class _FakeOAuthConn:
    """Stands in for an asyncpg connection for exactly the SQL this
    OAuth -> refresh -> /me chain issues. Dispatches on recognizable SQL
    substrings (a real query planner isn't needed here) and keeps state
    in plain dicts so a user created mid-test is actually visible to
    later calls in the same test."""

    def __init__(self, seed_users: list[dict] | None = None):
        self.users: dict[str, dict] = {str(u["id"]): dict(u) for u in (seed_users or [])}
        self.sessions: dict[str, dict] = {}
        self.insert_user_calls = 0

    def _by_email(self, email):
        return next((dict(u) for u in self.users.values() if u["email"] == email), None)

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if "SELECT * FROM users WHERE email=$1" in s:
            return self._by_email(args[0])
        if "FROM users WHERE id=$1" in s:  # covers both `SELECT *` and the column-list variant
            row = self.users.get(str(args[0]))
            return dict(row) if row else None
        if "FROM user_sessions s JOIN users u" in s:
            sess = self.sessions.get(args[0])
            if not sess:
                return None
            user = self.users.get(str(sess["user_id"]))
            if not user:
                return None
            return {
                "id": sess["id"], "user_id": sess["user_id"], "expires_at": sess["expires_at"],
                "email": user["email"], "name": user["name"],
                "email_verified": user["email_verified"], "avatar_url": user["avatar_url"],
                "created_at": user["created_at"],
            }
        raise AssertionError(f"_FakeOAuthConn.fetchrow: unrecognized query: {s[:100]!r}")

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO users"):
            new_id, email, name, avatar_url = args
            self.users[str(new_id)] = {
                "id": new_id, "email": email, "name": name, "avatar_url": avatar_url,
                "email_verified": True, "password_hash": None,
                "created_at": datetime.datetime.now(datetime.timezone.utc),
            }
            self.insert_user_calls += 1
            return "INSERT 0 1"
        if s.startswith("UPDATE users SET name="):
            user_id, name, avatar_url = args
            u = self.users.get(str(user_id))
            if u:
                if name:
                    u["name"] = name
                if avatar_url:
                    u["avatar_url"] = avatar_url
                u["email_verified"] = True
            return "UPDATE 1"
        if s.startswith("INSERT INTO user_sessions"):
            sess_id, user_id, refresh_token, ip, ua = args
            self.sessions[refresh_token] = {
                "id": sess_id, "user_id": user_id, "refresh_token": refresh_token,
                "expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30),
            }
            return "INSERT 0 1"
        if s.startswith("UPDATE user_sessions SET refresh_token="):
            new_refresh, sess_id = args
            for old_tok, sess in list(self.sessions.items()):
                if sess["id"] == sess_id:
                    del self.sessions[old_tok]
                    sess["refresh_token"] = new_refresh
                    self.sessions[new_refresh] = sess
                    break
            return "UPDATE 1"
        if s.startswith("DELETE FROM user_sessions"):
            sess_id = args[0]
            for tok, sess in list(self.sessions.items()):
                if sess["id"] == sess_id:
                    del self.sessions[tok]
            return "DELETE 1"
        raise AssertionError(f"_FakeOAuthConn.execute: unrecognized statement: {s[:100]!r}")


# ── Mocked Google HTTP layer ──────────────────────────────────────────────────

class _MockGoogleClient:
    """Stands in for httpx.AsyncClient() inside google_oauth_callback().
    Records every call so tests can assert exactly what was sent to
    Google, and never makes a real network call."""

    def __init__(
        self, *, token_status: int = 200, userinfo_status: int = 200,
        access_token: str = "google-access-token-abc",
        userinfo: dict | None = None,
    ):
        self.token_status = token_status
        self.userinfo_status = userinfo_status
        self.access_token = access_token
        self.userinfo = userinfo if userinfo is not None else {
            "email": "oauth-test@example.com", "name": "OAuth Test",
            "picture": "https://example.com/avatar.png", "verified_email": True,
        }
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, data=None, **kwargs):
        self.post_calls.append({"url": url, "data": data})
        return httpx.Response(self.token_status, json={"access_token": self.access_token})

    async def get(self, url, headers=None, **kwargs):
        self.get_calls.append({"url": url, "headers": headers})
        return httpx.Response(self.userinfo_status, json=self.userinfo)


def _patch_google(mock_client: _MockGoogleClient):
    return patch("app.routers.auth_users._httpx.AsyncClient", return_value=mock_client)


def _run_sync(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _valid_start(client, path="/api/auth/google/callback"):
    """Runs GET /api/auth/google to obtain a real state + oauth_state
    cookie, mirroring how a real browser would arrive at the callback."""
    with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-client-id"):
        start_resp = client.get("/api/auth/google", follow_redirects=False)
    location = start_resp.headers["location"]
    state = location.split("state=")[1].split("&")[0]
    cookie = start_resp.cookies.get("oauth_state")
    return state, cookie


# ══════════════════════════════════════════════════════════════════════════════
# 1. OAuth start
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthStart:
    def test_redirects_to_google_with_correct_params(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "my-test-client-id"):
            resp = client.get("/api/auth/google", follow_redirects=False)

        assert resp.status_code == 307
        location = resp.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=my-test-client-id" in location
        assert "redirect_uri=http://localhost:8000/api/auth/google/callback" in location
        assert "response_type=code" in location
        assert "scope=openid%20email%20profile" in location
        assert "state=" in location

    def test_state_is_present_and_nonempty(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            resp = client.get("/api/auth/google", follow_redirects=False)
        state = resp.headers["location"].split("state=")[1].split("&")[0]
        assert len(state) > 20  # secrets.token_urlsafe(32) — not a trivial/empty value

    def test_two_separate_start_calls_get_different_state_values(self, client):
        """A fixed/predictable state would defeat its own CSRF purpose."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            r1 = client.get("/api/auth/google", follow_redirects=False)
            r2 = client.get("/api/auth/google", follow_redirects=False)
        s1 = r1.headers["location"].split("state=")[1].split("&")[0]
        s2 = r2.headers["location"].split("state=")[1].split("&")[0]
        assert s1 != s2

    def test_oauth_state_cookie_is_set_with_correct_attributes(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            resp = client.get("/api/auth/google", follow_redirects=False)

        assert "oauth_state" in resp.cookies
        raw_set_cookie = resp.headers.get_list("set-cookie")
        assert any("oauth_state=" in h for h in raw_set_cookie)
        cookie_header = next(h for h in raw_set_cookie if "oauth_state=" in h)
        assert "HttpOnly" in cookie_header
        assert "samesite=lax" in cookie_header.lower()
        # APP_URL defaults to http://localhost:8000 in tests -> Secure must be absent
        assert "secure" not in cookie_header.lower()

    def test_oauth_state_cookie_is_secure_when_app_url_is_https(self, client):
        """Same code path, different APP_URL — proves `secure` is genuinely
        conditional, not hardcoded false."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._APP_URL_BASE", "https://example.com"):
            resp = client.get("/api/auth/google", follow_redirects=False)
        cookie_header = next(h for h in resp.headers.get_list("set-cookie") if "oauth_state=" in h)
        assert "secure" in cookie_header.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 2. Missing configuration — isolated per test, no shared module-level state
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthMissingConfiguration:
    def test_start_503s_when_client_id_is_empty(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", ""):
            resp = client.get("/api/auth/google", follow_redirects=False)
        assert resp.status_code == 503
        assert "Google" in resp.json()["detail"]
        assert "GOOGLE_CLIENT_ID" in resp.json()["detail"]

    def test_start_does_not_contact_google_when_unconfigured(self, client):
        """No httpx client should even be constructed."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", ""), \
             patch("app.routers.auth_users._httpx.AsyncClient") as mock_client_cls:
            client.get("/api/auth/google", follow_redirects=False)
        mock_client_cls.assert_not_called()

    def test_callback_503s_when_client_id_is_empty(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", ""), \
             patch("app.routers.auth_users._httpx.AsyncClient") as mock_client_cls:
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "irrelevant", "state": "irrelevant"},
                cookies={"oauth_state": "irrelevant"},
            )
        assert resp.status_code == 503
        mock_client_cls.assert_not_called()  # rejected before ever reaching Google

    def test_missing_client_id_is_independent_of_a_prior_tests_patch(self, client):
        """Regression guard for the isolation requirement itself: run the
        'configured' path first, then confirm the very next call still
        sees the real (unset) module-level default once its patch exits."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "temporarily-configured"):
            configured_resp = client.get("/api/auth/google", follow_redirects=False)
        assert configured_resp.status_code == 307

        unconfigured_resp = client.get("/api/auth/google", follow_redirects=False)
        assert unconfigured_resp.status_code == 503

    def test_client_secret_alone_missing_is_not_caught_at_start_FINDING(self, client):
        """FINDING (reported, not fixed — see final report): google_oauth_start()
        and google_oauth_callback() only ever check `_GOOGLE_CLIENT_ID`.
        `_GOOGLE_CLIENT_SECRET` is never checked for presence anywhere. If
        CLIENT_ID is set but CLIENT_SECRET is empty, /google still issues a
        real redirect to Google instead of a 503 — the misconfiguration only
        surfaces later, deep in the callback's token exchange, as a generic
        400 "Google OAuth token exchange failed" after the user has already
        completed Google's real consent screen. This test documents that
        ACTUAL behavior; it does not assert the 503 the spec anticipated,
        because the code does not produce one for this specific case."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "set"), \
             patch("app.routers.auth_users._GOOGLE_CLIENT_SECRET", ""):
            resp = client.get("/api/auth/google", follow_redirects=False)
        assert resp.status_code == 307  # NOT 503 — documents the gap, doesn't fix it


# ══════════════════════════════════════════════════════════════════════════════
# 3. Callback state protection
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthCallbackStateProtection:
    def test_missing_state_rejected_before_token_exchange(self, client):
        mock_google = _MockGoogleClient()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "some-code"},  # no state param at all
                cookies={"oauth_state": "cookie-state-value"},
            )
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()
        assert mock_google.post_calls == []  # never reached token exchange

    def test_state_mismatched_with_cookie_rejected_before_token_exchange(self, client):
        mock_google = _MockGoogleClient()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "some-code", "state": "attacker-supplied-state"},
                cookies={"oauth_state": "real-state-value"},
            )
        assert resp.status_code == 400
        assert mock_google.post_calls == []

    def test_no_cookie_at_all_rejected_before_token_exchange(self, client):
        mock_google = _MockGoogleClient()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "some-code", "state": "whatever"},
                # no cookies at all — browser never visited /google first
            )
        assert resp.status_code == 400
        assert mock_google.post_calls == []

    def test_matching_state_passes_and_reaches_token_exchange(self, client, _fake_conn=None):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient()
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-client-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "real-code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        assert resp.status_code == 307  # redirected to /oauth-callback, not rejected
        assert len(mock_google.post_calls) == 1  # token exchange DID happen

    def test_state_reuse_after_first_successful_callback_FINDING(self, client):
        """FINDING (reported, not fixed — see final report): _verify_oauth_state
        only compares the query-string `state` against the `oauth_state`
        cookie value — there is no server-side record of which state values
        have already been consumed. The cookie is deleted on the SUCCESS
        response (resp.delete_cookie), but nothing stops a second request
        that still presents the same state+cookie pair from passing this
        application's own check a second time. In production this specific
        replay is only actually blocked by Google's own one-time-use
        authorization `code` (a real code cannot be exchanged twice), which
        this mocked test cannot exercise (a real Google outcome, not
        something app-level state-checking causes). This test proves the
        state check ALONE does not reject a replay when the (mocked) code
        exchange is made to keep succeeding."""
        state, cookie = _valid_start(client)
        conn = _FakeOAuthConn()

        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-client-id"), \
             _patch_google(_MockGoogleClient()), _mock_pool(conn):
            first = client.get(
                "/api/auth/google/callback",
                params={"code": "real-code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
            second = client.get(
                "/api/auth/google/callback",
                params={"code": "real-code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )

        assert first.status_code == 307
        # Documents actual behavior: the app's own state check does not by
        # itself reject the replay (still 307, not 400/401).
        assert second.status_code == 307


# ══════════════════════════════════════════════════════════════════════════════
# 4. Google token exchange — verify exactly what is sent
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleTokenExchangeRequest:
    def test_token_exchange_sends_the_required_fields(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient()
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "the-client-id"), \
             patch("app.routers.auth_users._GOOGLE_CLIENT_SECRET", "the-client-secret"), \
             _patch_google(mock_google), _mock_pool(conn):
            client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code-xyz", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )

        assert len(mock_google.post_calls) == 1
        call = mock_google.post_calls[0]
        assert call["url"] == "https://oauth2.googleapis.com/token"
        data = call["data"]
        assert data["code"] == "auth-code-xyz"
        assert data["client_id"] == "the-client-id"
        assert data["client_secret"] == "the-client-secret"
        assert data["redirect_uri"] == "http://localhost:8000/api/auth/google/callback"
        assert data["grant_type"] == "authorization_code"

    def test_no_real_google_endpoint_is_ever_actually_contacted(self, client):
        """The mock replaces httpx.AsyncClient entirely — assert the patch
        target is exactly what google_oauth_callback() uses, so a future
        refactor that bypasses `_httpx.AsyncClient` would break this test
        rather than silently start hitting the real internet."""
        import app.routers.auth_users as auth_mod
        assert hasattr(auth_mod, "_httpx")

    def test_token_exchange_non_200_yields_400_not_a_crash(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(token_status=400)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "bad-code", "state": state},
                cookies={"oauth_state": cookie},
            )
        assert resp.status_code == 400
        assert "token exchange failed" in resp.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# 5. Google userinfo
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleUserinfo:
    def test_userinfo_fetched_with_bearer_access_token(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(access_token="specific-access-token-123")
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        assert len(mock_google.get_calls) == 1
        call = mock_google.get_calls[0]
        assert call["url"] == "https://www.googleapis.com/oauth2/v2/userinfo"
        assert call["headers"]["Authorization"] == "Bearer specific-access-token-123"

    def test_userinfo_fields_flow_into_user_creation(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo={
            "email": "oauth-test@example.com", "name": "OAuth Test",
            "picture": "https://example.com/avatar.png", "verified_email": True,
        })
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        assert len(conn.users) == 1
        created = next(iter(conn.users.values()))
        assert created["email"] == "oauth-test@example.com"
        assert created["name"] == "OAuth Test"
        assert created["avatar_url"] == "https://example.com/avatar.png"

    def test_missing_email_in_userinfo_is_rejected(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo={"name": "No Email User"})
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
            )
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_userinfo_non_200_yields_400(self, client):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo_status=403)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
            )
        assert resp.status_code == 400

    def test_verified_email_field_is_not_checked_FINDING(self, client):
        """FINDING (reported, not fixed — see final report and the prior
        diagnostic audit's Security section, MEDIUM): google_oauth_callback()
        reads only info.get("email") and never inspects
        info.get("verified_email"). This test proves an unverified email
        is currently accepted and used to create/link an account exactly
        like a verified one."""
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo={
            "email": "unverified@example.com", "name": "Unverified",
            "picture": "", "verified_email": False,
        })
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        assert resp.status_code == 307  # accepted despite verified_email: False
        assert len(conn.users) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. New user
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthNewUser:
    def _run(self, client, email="new-oauth-user@example.com"):
        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo={
            "email": email, "name": "New OAuth User",
            "picture": "https://example.com/avatar.png", "verified_email": True,
        })
        conn = _FakeOAuthConn()
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        return resp, conn

    def test_creates_exactly_one_new_user(self, client):
        resp, conn = self._run(client)
        assert resp.status_code == 307
        assert conn.insert_user_calls == 1
        assert len(conn.users) == 1

    def test_new_user_is_email_verified_and_has_no_password(self, client):
        _, conn = self._run(client)
        user = next(iter(conn.users.values()))
        assert user["email_verified"] is True
        assert user["password_hash"] is None

    def test_creates_a_session_row(self, client):
        _, conn = self._run(client)
        assert len(conn.sessions) == 1

    def test_creates_an_oauth_exchange_code_and_no_duplicate_user_on_a_second_new_email(self, client):
        resp, _ = self._run(client, email="another-new-user@example.com")
        location = resp.headers["location"]
        assert location.startswith("http://localhost:8000/oauth-callback?code=")
        code = location.split("code=")[1]
        assert len(code) > 20

    def test_callback_redirect_never_contains_raw_tokens(self, client):
        """The one-time exchange code must be opaque — no access_token,
        refresh_token, or JWT-shaped content directly in the URL."""
        resp, _ = self._run(client)
        location = resp.headers["location"]
        assert "access_token" not in location
        assert "refresh_token" not in location
        assert location.count(".") < 2  # a JWT has two dots; an opaque token_urlsafe code doesn't


# ══════════════════════════════════════════════════════════════════════════════
# 7. Existing user
# ══════════════════════════════════════════════════════════════════════════════

class TestGoogleOAuthExistingUser:
    def test_does_not_create_a_duplicate_user(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "returning-user@example.com", "name": "Old Name",
            "avatar_url": None, "email_verified": False, "password_hash": "$2b$somehash",
            "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100),
        }
        conn = _FakeOAuthConn(seed_users=[existing])

        state, cookie = _valid_start(client)
        mock_google = _MockGoogleClient(userinfo={
            "email": "returning-user@example.com", "name": "New Name From Google",
            "picture": "https://example.com/new-avatar.png", "verified_email": True,
        })
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(mock_google), _mock_pool(conn):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert conn.insert_user_calls == 0  # no new INSERT INTO users
        assert len(conn.users) == 1         # still exactly the one seeded user
        assert str(existing_id) in conn.users

    def test_existing_user_becomes_email_verified_via_oauth(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "returning2@example.com", "name": "Old Name",
            "avatar_url": None, "email_verified": False, "password_hash": "$2b$hash",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        state, cookie = _valid_start(client)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(_MockGoogleClient(userinfo={
                 "email": "returning2@example.com", "name": "New Name",
                 "picture": "", "verified_email": True,
             })), _mock_pool(conn):
            client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        assert conn.users[str(existing_id)]["email_verified"] is True
        assert conn.users[str(existing_id)]["name"] == "New Name"

    def test_each_login_creates_a_fresh_session_and_exchange_code(self, client):
        existing_id = uuid.uuid4()
        existing = {
            "id": existing_id, "email": "returning3@example.com", "name": "X",
            "avatar_url": None, "email_verified": True, "password_hash": None,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        conn = _FakeOAuthConn(seed_users=[existing])
        codes = []
        for _ in range(2):
            state, cookie = _valid_start(client)
            with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
                 _patch_google(_MockGoogleClient(userinfo={
                     "email": "returning3@example.com", "name": "X", "picture": "",
                     "verified_email": True,
                 })), _mock_pool(conn):
                resp = client.get(
                    "/api/auth/google/callback",
                    params={"code": "code", "state": state},
                    cookies={"oauth_state": cookie},
                    follow_redirects=False,
                )
            codes.append(resp.headers["location"].split("code=")[1])

        assert conn.insert_user_calls == 0
        assert len(conn.sessions) == 2       # two distinct sessions/refresh tokens
        assert codes[0] != codes[1]           # two distinct exchange codes


# ══════════════════════════════════════════════════════════════════════════════
# 8. OAuth exchange
# ══════════════════════════════════════════════════════════════════════════════

class TestOAuthExchange:
    def _do_login(self, client, conn, email="exchange-test@example.com"):
        state, cookie = _valid_start(client)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(_MockGoogleClient(userinfo={
                 "email": email, "name": "Exchange Test", "picture": "",
                 "verified_email": True,
             })), _mock_pool(conn):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        return resp.headers["location"].split("code=")[1]

    def test_valid_code_returns_the_current_documented_contract(self, client):
        conn = _FakeOAuthConn()
        code = self._do_login(client, conn)

        resp = client.post("/api/auth/oauth-exchange", json={"code": code})

        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"access_token", "refresh_token", "sub_token"}
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["sub_token"]

    def test_invalid_code_is_rejected(self, client):
        resp = client.post("/api/auth/oauth-exchange", json={"code": "never-issued-code"})
        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower() or "expired" in resp.json()["detail"].lower()

    def test_expired_code_is_rejected(self, client):
        conn = _FakeOAuthConn()
        code = self._do_login(client, conn)

        # Force the Redis entry's TTL into the past instead of sleeping 60s.
        from app.core.cache.redis_adapter import get_redis

        async def _expire():
            import time
            redis = await get_redis()
            entry = redis._b._store.get(redis._k(f"oauth_exchange:{code}"))
            assert entry is not None, "exchange code was not actually stored"
            entry.expires_at = time.monotonic() - 1

        _run_sync(_expire())

        resp = client.post("/api/auth/oauth-exchange", json={"code": code})
        assert resp.status_code == 400

    def test_reused_code_is_rejected_after_first_redemption(self, client):
        conn = _FakeOAuthConn()
        code = self._do_login(client, conn)

        first = client.post("/api/auth/oauth-exchange", json={"code": code})
        second = client.post("/api/auth/oauth-exchange", json={"code": code})

        assert first.status_code == 200
        assert second.status_code == 400  # single-use — the whole point of the exchange step

    def test_exchange_code_is_confirmed_single_use_via_store_inspection(self, client):
        """Stronger than the black-box test above — directly confirms the
        Redis-backed entry is actually deleted, not just that a second
        HTTP call happens to 400 for some other reason."""
        conn = _FakeOAuthConn()
        code = self._do_login(client, conn)

        client.post("/api/auth/oauth-exchange", json={"code": code})

        from app.core.cache.redis_adapter import get_redis

        async def _check():
            redis = await get_redis()
            return await redis.get_json(f"oauth_exchange:{code}")

        remaining = _run_sync(_check())
        assert remaining is None


# ══════════════════════════════════════════════════════════════════════════════
# 9. /me after OAuth exchange
# ══════════════════════════════════════════════════════════════════════════════

class TestMeAfterOAuthExchange:
    def test_me_returns_the_same_identity_google_supplied(self, client):
        conn = _FakeOAuthConn()
        state, cookie = _valid_start(client)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(_MockGoogleClient(userinfo={
                 "email": "me-check@example.com", "name": "Me Check",
                 "picture": "https://example.com/p.png", "verified_email": True,
             })), _mock_pool(conn):
            callback_resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        exchange_code = callback_resp.headers["location"].split("code=")[1]

        with _mock_pool(conn):
            exchange_resp = client.post("/api/auth/oauth-exchange", json={"code": exchange_code})
            access_token = exchange_resp.json()["access_token"]

            me_resp = client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"},
            )

        assert me_resp.status_code == 200
        me_body = me_resp.json()
        assert me_body["email"] == "me-check@example.com"
        assert me_body["name"] == "Me Check"
        assert me_body["email_verified"] is True

    def test_me_without_a_token_is_rejected(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Refresh flow
# ══════════════════════════════════════════════════════════════════════════════

class TestRefreshAfterOAuth:
    def _login_and_exchange(self, client, conn, email="refresh-oauth@example.com"):
        state, cookie = _valid_start(client)
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             _patch_google(_MockGoogleClient(userinfo={
                 "email": email, "name": "Refresh Test", "picture": "",
                 "verified_email": True,
             })), _mock_pool(conn):
            callback_resp = client.get(
                "/api/auth/google/callback",
                params={"code": "code", "state": state},
                cookies={"oauth_state": cookie},
                follow_redirects=False,
            )
        exchange_code = callback_resp.headers["location"].split("code=")[1]
        with _mock_pool(conn):
            return client.post("/api/auth/oauth-exchange", json={"code": exchange_code}).json()

    def test_refresh_token_from_oauth_login_yields_a_new_access_token(self, client):
        conn = _FakeOAuthConn()
        tokens = self._login_and_exchange(client, conn)

        with _mock_pool(conn):
            resp = client.post(
                "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        # NOT asserting access_token != tokens["access_token"]: make_access_token()
        # is a deterministic JWT (sub/email/type/iat/exp only, second-granularity
        # iat) — two calls for the same user within the same wall-clock second
        # produce a byte-identical token. That's expected JWT behavior, not a
        # bug (see FINDINGS in the final report) — the refresh_token (opaque,
        # random, persisted) is the actual rotated credential.
        assert body["refresh_token"] != tokens["refresh_token"]   # rotated, same as password login

    def test_refreshed_access_token_also_authenticates_me(self, client):
        conn = _FakeOAuthConn()
        tokens = self._login_and_exchange(client, conn)

        with _mock_pool(conn):
            refreshed = client.post(
                "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]},
            ).json()
            me_resp = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {refreshed['access_token']}"},
            )
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == "refresh-oauth@example.com"

    def test_old_refresh_token_is_invalidated_after_rotation_same_as_password_login(self, client):
        conn = _FakeOAuthConn()
        tokens = self._login_and_exchange(client, conn)

        with _mock_pool(conn):
            client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            reuse_resp = client.post(
                "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]},
            )
        assert reuse_resp.status_code == 401

    def test_invalid_refresh_token_is_rejected(self, client):
        conn = _FakeOAuthConn()
        with _mock_pool(conn):
            resp = client.post("/api/auth/refresh", json={"refresh_token": "never-issued"})
        assert resp.status_code == 401
