"""
HTTP-level integration tests for /api/auth/* endpoints.

Uses FastAPI's TestClient with a mocked DB pool so no live Postgres is needed.
Covers: registration, login, token refresh, /me, 401 on missing/bad token,
rate-limit headers, and input validation.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure required env vars are present before importing the app
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers.auth_users import router  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app():
    """Minimal FastAPI app with only the auth router mounted."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _mock_pool(conn_mock):
    """Context manager that patches get_pool() to return a fake pool."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.auth_users.get_pool", return_value=pool)


# ── C-01 regression: rate limiting on auth endpoints ─────────────────────────

class TestAuthRateLimit:
    def test_login_rate_limited_after_10_attempts(self, client):
        """The 11th login attempt from the same IP must return 429."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # user not found → 401

        with _mock_pool(conn):
            responses = [
                client.post(
                    "/api/auth/login",
                    json={"email": "x@x.com", "password": "wrongpw"},
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                for _ in range(11)
            ]

        status_codes = [r.status_code for r in responses]
        # First 10 must not be 429
        assert all(c != 429 for c in status_codes[:10]), (
            f"Rate limit triggered too early: {status_codes}"
        )
        # 11th must be 429
        assert responses[10].status_code == 429, (
            f"Expected 429 on 11th attempt, got {responses[10].status_code}"
        )
        assert responses[10].headers.get("Retry-After") == "60"

    def test_register_rate_limited(self, client):
        """Register endpoint must 429 after 10 attempts."""
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=None)
        conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.hash_password", return_value="$hashed"), \
             patch("app.routers.auth_users.send_verification_email", new_callable=AsyncMock), \
             patch("app.routers.auth_users.write_audit", new_callable=AsyncMock):
            responses = [
                client.post(
                    "/api/auth/register",
                    json={"name": "Test", "email": f"u{i}@x.com", "password": "ValidPass1"},
                    headers={"X-Forwarded-For": "5.6.7.8"},
                )
                for i in range(11)
            ]

        assert responses[10].status_code == 429

    def test_forgot_password_rate_limited(self, client):
        """Forgot-password must 429 after 10 attempts."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # user not found → safe response

        with _mock_pool(conn), \
             patch("app.routers.auth_users.send_password_reset_email", new_callable=AsyncMock):
            responses = [
                client.post(
                    "/api/auth/forgot-password",
                    json={"email": "victim@x.com"},
                    headers={"X-Forwarded-For": "9.10.11.12"},
                )
                for _ in range(11)
            ]

        assert responses[10].status_code == 429


# ── 401 on protected endpoints without token ──────────────────────────────────

class TestAuthGate:
    def test_get_me_requires_bearer(self, client):
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_get_me_with_bad_token_returns_401(self, client):
        res = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert res.status_code == 401

    def test_logout_all_requires_bearer(self, client):
        res = client.post("/api/auth/logout-all")
        assert res.status_code == 401


# ── Input validation ──────────────────────────────────────────────────────────

class TestInputValidation:
    def test_register_rejects_short_password(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "t@t.com", "password": "short"},
        )
        assert res.status_code == 422

    def test_register_rejects_invalid_email(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "not-an-email", "password": "ValidPass1"},
        )
        assert res.status_code == 422

    def test_register_rejects_empty_name(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "   ", "email": "t@t.com", "password": "ValidPass1"},
        )
        assert res.status_code == 422

    def test_login_rejects_missing_fields(self, client):
        res = client.post("/api/auth/login", json={"email": "t@t.com"})
        assert res.status_code == 422

    def test_forgot_password_rejects_invalid_email(self, client):
        res = client.post(
            "/api/auth/forgot-password",
            json={"email": "not-email"},
        )
        assert res.status_code == 422


# ── Login happy path ──────────────────────────────────────────────────────────

class TestLoginHappyPath:
    def test_valid_credentials_return_tokens(self, client):
        fake_user = {
            "id": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
            "email": "user@example.com",
            "name": "User",
            "password_hash": "$bcrypt_hash",
            "email_verified": True,
            "avatar_url": None,
            "created_at": None,
        }
        # Make dict-like access work
        user_row = MagicMock()
        user_row.__getitem__ = MagicMock(side_effect=fake_user.__getitem__)
        user_row.get = MagicMock(side_effect=fake_user.get)

        async def _fetchrow(query, *args):
            # Login also checks mfa_secrets — simulate "no MFA configured"
            # (a None row) for this user, distinct from the user lookup.
            if "mfa_secrets" in query:
                return None
            return user_row

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        conn.execute = AsyncMock(return_value=None)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.verify_password", return_value=True), \
             patch("app.routers.auth_users.make_access_token", return_value="access.tok.en"), \
             patch("app.routers.auth_users.make_refresh_token", return_value="refresh.token"), \
             patch("app.routers.auth_users.write_audit", new_callable=AsyncMock):
            res = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "ValidPass1"},
                headers={"X-Forwarded-For": "77.1.2.3"},
            )

        assert res.status_code == 200
        body = res.json()
        assert body["access_token"] == "access.tok.en"
        assert body["refresh_token"] == "refresh.token"
        assert body["token_type"] == "bearer"

    def test_wrong_password_returns_401(self, client):
        fake_user = MagicMock()
        fake_user.__getitem__ = MagicMock(side_effect={"password_hash": "$hash"}.__getitem__)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=fake_user)

        with _mock_pool(conn), \
             patch("app.routers.auth_users.verify_password", return_value=False):
            res = client.post(
                "/api/auth/login",
                json={"email": "user@example.com", "password": "WrongPassword"},
                headers={"X-Forwarded-For": "88.1.2.3"},
            )

        assert res.status_code == 401


# ── M-13 regression: rate limiter must use rightmost XFF IP (not spoofable) ───

class TestRateLimitXFFSpoofing:
    """Verify the rate limiter uses the rightmost X-Forwarded-For IP (M-13).

    Render's proxy appends the real client IP as the last entry.  An attacker
    can prepend any number of fake IPs before it.  The rate limiter must ignore
    those and key on the rightmost (real) IP so that spoofing cannot bypass
    the per-IP limit.
    """

    @staticmethod
    def _make_req(xff: str):
        """Create a minimal mock Starlette Request with the given X-Forwarded-For value."""
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers.get = lambda name, default="": xff if name == "X-Forwarded-For" else default
        req.client.host = "10.0.0.1"  # internal LB
        return req

    def test_rightmost_xff_triggers_limit(self):
        """10 requests with same real (rightmost) IP saturate the limit; 11th is 429."""
        from fastapi import HTTPException
        from app.core.rate_limit import require_rate_limit, rl_store

        rl_store.clear()
        try:
            # Rightmost IP is always "200.0.0.1"; leftmost varies (spoofed)
            for i in range(10):
                require_rate_limit(
                    self._make_req(f"1.1.1.{i}, 200.0.0.1"),
                    key_prefix="m13_a", max_calls=10, window=60,
                )

            with pytest.raises(HTTPException) as exc:
                require_rate_limit(
                    self._make_req("1.1.1.99, 200.0.0.1"),
                    key_prefix="m13_a", max_calls=10, window=60,
                )
            assert exc.value.status_code == 429
        finally:
            rl_store.clear()

    def test_different_real_ips_are_not_conflated(self):
        """Two real IPs each get their own counter; changing real IP resets budget."""
        from app.core.rate_limit import require_rate_limit, rl_store

        rl_store.clear()
        try:
            # 10 requests from real IP A — should not limit real IP B
            for _ in range(10):
                require_rate_limit(
                    self._make_req("spoofed, 1.2.3.4"),
                    key_prefix="m13_b", max_calls=10, window=60,
                )

            # First request from real IP B must still be allowed
            require_rate_limit(
                self._make_req("spoofed, 5.6.7.8"),
                key_prefix="m13_b", max_calls=10, window=60,
            )  # must NOT raise
        finally:
            rl_store.clear()


# ── Reliability regression: OAuth callbacks must not leak raw 500s on a
#    provider network failure — only HTTP-status branches were handled;
#    a connection error/timeout talking to Google/Microsoft/GitHub had no
#    try/except and propagated as an unhandled exception. ─────────────────────

class _UnreachableProviderClient:
    """Stands in for httpx.AsyncClient(); every call raises a connection
    error, simulating the OAuth provider being unreachable."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ConnectError("connection refused")

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("connection refused")


class TestOAuthCallbackProviderUnreachable:
    """A network-level failure reaching the OAuth provider must produce a
    clean 502, not an unhandled 500."""

    @staticmethod
    def _get_callback(client, path: str, state: str = "state-value"):
        return client.get(
            path,
            params={"code": "auth-code", "state": state},
            cookies={"oauth_state": state},
        )

    def test_google_callback_502_on_connect_error(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp = self._get_callback(client, "/api/auth/google/callback")

        assert resp.status_code == 502
        assert "Google" in resp.json()["detail"]

    def test_microsoft_callback_502_on_connect_error(self, client):
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp = self._get_callback(client, "/api/auth/microsoft/callback")

        assert resp.status_code == 502
        assert "Microsoft" in resp.json()["detail"]

    def test_github_callback_502_on_connect_error(self, client):
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp = self._get_callback(client, "/api/auth/github/callback")

        assert resp.status_code == 502
        assert "GitHub" in resp.json()["detail"]

    def test_google_callback_still_400s_on_bad_state(self, client):
        """Provider-unreachable handling must not swallow the existing
        CSRF-state check — a mismatched state must still 400, not 502."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": "attacker-supplied"},
                cookies={"oauth_state": "state-value"},
            )

        assert resp.status_code == 400


# ── Regression: a non-200 from the token-exchange/userinfo call must be
#    LOGGED with the provider's real error before the generic 400 is
#    raised — previously the real reason (bad client_secret, redirect_uri
#    mismatch, expired/reused code, provider-side rejection) was silently
#    discarded, leaving only an undifferentiated "Google OAuth token
#    exchange failed" with nothing to debug from. ─────────────────────────────

class _JsonResponseClient:
    """Stands in for httpx.AsyncClient(); every call returns a fixed
    (status_code, json_body) response regardless of URL, so these tests can
    target the token-exchange failure without needing a resolvable second
    call to succeed."""

    def __init__(self, status_code: int, json_body: dict, text: str | None = None):
        self._status_code = status_code
        self._json_body = json_body
        self._text = text if text is not None else str(json_body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    class _Response:
        def __init__(self, status_code, json_body, text):
            self.status_code = status_code
            self._json_body = json_body
            self.text = text

        def json(self):
            return self._json_body

    async def post(self, *args, **kwargs):
        return self._Response(self._status_code, self._json_body, self._text)

    async def get(self, *args, **kwargs):
        return self._Response(self._status_code, self._json_body, self._text)


class TestAppUrlTrailingSlashNormalized:
    """A trailing slash on the APP_URL env var (an easy, otherwise-silent
    misconfiguration) must not produce a double-slash redirect_uri --
    Google/Microsoft/GitHub compare redirect_uri byte-for-byte against what
    was registered, so a double slash breaks the token exchange with no
    obvious client-visible cause.

    Deliberately does NOT importlib.reload(app.routers.auth_users) to test
    this -- reloading recreates every function object in the module
    (get_current_user included), which breaks identity-based checks
    elsewhere in the suite (e.g. test_enterprise.py's
    `Depends(get_current_user)` `is` comparison, whose captured reference
    is bound at api_keys_router's own import time). The normalization is
    tested as the pure function it actually is instead."""

    def test_normalize_strips_trailing_slash(self):
        from app.routers.auth_users import _normalize_app_url_base
        assert _normalize_app_url_base("https://example.com/") == "https://example.com"

    def test_normalize_is_a_noop_without_trailing_slash(self):
        from app.routers.auth_users import _normalize_app_url_base
        assert _normalize_app_url_base("https://example.com") == "https://example.com"

    def test_normalize_strips_only_trailing_slashes_not_path_slashes(self):
        from app.routers.auth_users import _normalize_app_url_base
        assert _normalize_app_url_base("https://example.com/app/") == "https://example.com/app"

    def test_currently_loaded_app_url_base_has_no_trailing_slash(self):
        """The module-level constant every redirect_uri is actually built
        from must itself be normalized -- proves the helper above is wired
        in, not just correct in isolation."""
        from app.routers.auth_users import _APP_URL_BASE
        assert not _APP_URL_BASE.endswith("/")

    def test_google_start_redirect_uri_has_no_double_slash(self, client):
        """End-to-end through the real, already-loaded module: whatever
        APP_URL this process started with, the redirect_uri Google sees
        must never contain a double slash before /api."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            resp = client.get("/api/auth/google", follow_redirects=False)
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert "//api/auth/google/callback" not in location


class TestOAuthTokenExchangeErrorIsLogged:
    @staticmethod
    def _get_callback(client, path: str, state: str = "state-value"):
        return client.get(
            path,
            params={"code": "auth-code", "state": state},
            cookies={"oauth_state": state},
        )

    def test_google_token_exchange_failure_logs_real_error(self, client, caplog):
        fake_client = _JsonResponseClient(
            400, {"error": "invalid_grant", "error_description": "Bad Request"},
        )
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._GOOGLE_CLIENT_SECRET", "fake-secret"), \
             patch("app.routers.auth_users._httpx.AsyncClient", return_value=fake_client), \
             caplog.at_level("WARNING", logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/google/callback")

        assert resp.status_code == 400
        assert "Google OAuth token exchange failed" in resp.json()["detail"]

        # The real Google-reported reason must be observable server-side...
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        joined = "\n".join(warnings)
        assert "invalid_grant" in joined
        assert "Bad Request" in joined
        assert "400" in joined
        # ...but the authorization code, client secret, and any token must
        # never appear in a log line, regardless of outcome.
        assert "fake-secret" not in joined
        assert "auth-code" not in joined

    def test_google_userinfo_failure_logs_real_error(self, client, caplog):
        """The token exchange succeeds; the userinfo call is what fails —
        must be logged distinctly from a token-exchange failure."""
        call_count = {"n": 0}

        class _MixedClient(_JsonResponseClient):
            async def post(self, *args, **kwargs):
                return self._Response(200, {"access_token": "gh-tok"}, "")

            async def get(self, *args, **kwargs):
                call_count["n"] += 1
                return self._Response(
                    401, {"error": {"code": 401, "message": "Invalid Credentials"}}, "",
                )

        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._GOOGLE_CLIENT_SECRET", "fake-secret"), \
             patch("app.routers.auth_users._httpx.AsyncClient", return_value=_MixedClient(0, {})), \
             caplog.at_level("WARNING", logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/google/callback")

        assert resp.status_code == 400
        assert "Failed to fetch Google user info" in resp.json()["detail"]
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        joined = "\n".join(warnings)
        assert "Invalid Credentials" in joined
        assert "userinfo" in joined
        assert "gh-tok" not in joined  # the access token itself must never be logged

    def test_microsoft_token_exchange_failure_logs_real_error(self, client, caplog):
        fake_client = _JsonResponseClient(
            401, {"error": "invalid_client", "error_description": "Invalid client secret"},
        )
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._MICROSOFT_CLIENT_SECRET", "fake-secret"), \
             patch("app.routers.auth_users._httpx.AsyncClient", return_value=fake_client), \
             caplog.at_level("WARNING", logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/microsoft/callback")

        assert resp.status_code == 400
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        joined = "\n".join(warnings)
        assert "invalid_client" in joined
        assert "Invalid client secret" in joined
        assert "fake-secret" not in joined

    def test_github_token_exchange_failure_logs_real_error(self, client, caplog):
        """GitHub's token endpoint can 200 with an error body instead of a
        non-200 status (e.g. a reused/expired code) — must still be
        logged, not just the plain non-200 case."""
        fake_client = _JsonResponseClient(
            200, {"error": "bad_verification_code",
                  "error_description": "The code passed is incorrect or expired."},
        )
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._GITHUB_CLIENT_SECRET", "fake-secret"), \
             patch("app.routers.auth_users._httpx.AsyncClient", return_value=fake_client), \
             caplog.at_level("WARNING", logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/github/callback")

        assert resp.status_code == 400
        assert "GitHub did not return an access token" in resp.json()["detail"]
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        joined = "\n".join(warnings)
        assert "bad_verification_code" in joined
        assert "expired" in joined
        assert "fake-secret" not in joined
