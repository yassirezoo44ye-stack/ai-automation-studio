"""
HTTP-level integration tests for /api/auth/* endpoints.

Uses FastAPI's TestClient with a mocked DB pool so no live Postgres is needed.
Covers: registration, login, token refresh, /me, 401 on missing/bad token,
rate-limit headers, and input validation.
"""
from __future__ import annotations

import logging
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


@pytest.fixture(autouse=True)
def _isolate_shared_singletons():
    """Reset the Redis adapter singleton before and after every test so
    oauth_state cache entries from one test never bleed into another."""
    import app.core.cache.redis_adapter as redis_adapter_mod
    redis_adapter_mod._instance = None
    yield
    redis_adapter_mod._instance = None


def _run_sync(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _stash_state(state: str, bind_nonce: str = "test-bind-nonce") -> None:
    """Pre-stash an OAuth state + bind nonce so callback tests can call the
    callback directly without going through the start endpoint."""
    from app.core.cache.redis_adapter import get_redis

    async def _do():
        redis = await get_redis()
        await redis.set(f"oauth_state:{state}", bind_nonce, ttl=600)

    _run_sync(_do())


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
    def _get_callback(client, path: str, state: str = "state-value", bind_nonce: str = "test-bind-nonce"):
        _stash_state(state, bind_nonce)
        return client.get(
            path,
            params={"code": "auth-code", "state": state},
            cookies={"oauth_bind": bind_nonce},
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
        """CSRF-state check fires before provider network call — an unknown
        state must still 400, not 502, even when the provider is unreachable."""
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": "attacker-supplied"},
                # "attacker-supplied" was never stashed → cache miss → 400
            )

        assert resp.status_code == 400


# ── Regression: Microsoft/GitHub token-exchange failures must log the
#    provider's actual error (same diagnostic gap Google's callback had,
#    same Option-B fix — log-only, client response unchanged) ────────────────

class _TokenErrorClient:
    """Returns a controllable JSON error body from the token endpoint,
    simulating what a provider actually sends on a rejected exchange (as
    opposed to _UnreachableProviderClient's connection-level failure)."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        return httpx.Response(self.status_code, json=self.body)

    async def get(self, *args, **kwargs):
        raise AssertionError("must not reach userinfo after a failed token exchange")


class TestOAuthTokenExchangeFailureLogging:
    @staticmethod
    def _get_callback(client, path: str, state: str = "state-value", bind_nonce: str = "test-bind-nonce"):
        _stash_state(state, bind_nonce)
        return client.get(path, params={"code": "auth-code", "state": state},
                          cookies={"oauth_bind": bind_nonce})

    def test_microsoft_callback_logs_actual_error_keeps_generic_response(self, client, caplog):
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_TokenErrorClient(400, {"error": "invalid_grant", "error_description": "code expired"})), \
             caplog.at_level(logging.WARNING, logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/microsoft/callback")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Microsoft OAuth token exchange failed"
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "invalid_grant" in logged
        assert "code expired" in logged

    def test_github_callback_logs_actual_error_keeps_generic_response(self, client, caplog):
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_TokenErrorClient(400, {"error": "bad_verification_code", "error_description": "bad code"})), \
             caplog.at_level(logging.WARNING, logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/github/callback")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "GitHub OAuth token exchange failed"
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "bad_verification_code" in logged
        assert "bad code" in logged

    def test_github_callback_200_with_no_access_token_logs_actual_error(self, client, caplog):
        """GitHub's specific quirk: a rejected exchange can come back as
        HTTP 200 with the error encoded in the body instead of a non-200
        status — a second, separate check in the code catches this."""
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_TokenErrorClient(200, {"error": "incorrect_client_credentials", "error_description": "bad client"})), \
             caplog.at_level(logging.WARNING, logger="app.routers.auth_users"):
            resp = self._get_callback(client, "/api/auth/github/callback")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "GitHub did not return an access token"
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "incorrect_client_credentials" in logged
        assert "bad client" in logged

    def test_no_secrets_or_codes_in_log_for_any_provider(self, client, caplog):
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._MICROSOFT_CLIENT_SECRET", "super-secret-value-xyz"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_TokenErrorClient(400, {"error": "invalid_client", "error_description": "d"})), \
             caplog.at_level(logging.WARNING, logger="app.routers.auth_users"):
            self._get_callback(client, "/api/auth/microsoft/callback")

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "super-secret-value-xyz" not in logged
        assert "auth-code" not in logged


# ── Login CSRF browser-binding (FINDING-1 fix) ────────────────────────────────


class TestOAuthLoginCSRFBrowserBinding:
    """Verify that the bind-nonce cookie prevents Login CSRF attacks
    (RFC 6749 §10.12) for all three providers."""

    PROVIDERS = [
        ("/api/auth/google/callback", "app.routers.auth_users._GOOGLE_CLIENT_ID"),
        ("/api/auth/microsoft/callback", "app.routers.auth_users._MICROSOFT_CLIENT_ID"),
        ("/api/auth/github/callback", "app.routers.auth_users._GITHUB_CLIENT_ID"),
    ]

    def test_login_csrf_attack_blocked_no_cookie(self, client):
        """Attacker stashes their own state in a fresh cache entry (simulating
        starting a flow in their own browser), then tricks the victim's browser
        into hitting the callback URL — but the victim's browser has NO
        oauth_bind cookie, so the callback must 400 before any token exchange."""
        state = "attacker-state-value"
        # Stash directly — do NOT use _valid_start through client so the client
        # cookie jar stays empty (no oauth_bind cookie planted).
        _stash_state(state, bind_nonce="attacker-bind-nonce")

        for path, cid_patch in self.PROVIDERS:
            # Reset cache so each provider has a fresh state entry
            _stash_state(state, bind_nonce="attacker-bind-nonce")
            with patch(cid_patch, "fake-id"):
                resp = client.get(
                    path,
                    params={"code": "auth-code", "state": state},
                    # deliberately NO cookies — victim has no oauth_bind
                )
            assert resp.status_code == 400, f"{path}: expected 400 got {resp.status_code}"

    def test_bind_nonce_mismatch_rejected(self, client):
        """State is valid in cache but attacker supplies wrong cookie value."""
        state = "csrf-state"
        _stash_state(state, bind_nonce="real-nonce")

        for path, cid_patch in self.PROVIDERS:
            _stash_state(state, bind_nonce="real-nonce")
            with patch(cid_patch, "fake-id"):
                resp = client.get(
                    path,
                    params={"code": "auth-code", "state": state},
                    cookies={"oauth_bind": "wrong-nonce"},  # mismatch
                )
            assert resp.status_code == 400, f"{path}: expected 400 got {resp.status_code}"

    def test_legitimate_flow_passes_bind_check(self, client):
        """Correct state + matching cookie must pass the bind check
        (provider network call is what causes the next error, not CSRF guard)."""
        state = "legit-state"
        nonce = "legit-nonce"

        for path, cid_patch in self.PROVIDERS:
            _stash_state(state, nonce)
            with patch(cid_patch, "fake-id"), \
                 patch("app.routers.auth_users._httpx.AsyncClient",
                       return_value=_UnreachableProviderClient()):
                resp = client.get(
                    path,
                    params={"code": "auth-code", "state": state},
                    cookies={"oauth_bind": nonce},
                )
            # CSRF guard passed → hits provider → 502 (not 400)
            assert resp.status_code == 502, f"{path}: expected 502 got {resp.status_code}"

    def test_no_cookie_does_not_consume_state(self, client):
        """A request with no oauth_bind cookie must be rejected BEFORE the cache
        get_and_delete_if_matches so the state remains available for the legitimate callback."""
        import asyncio as _asyncio
        from app.core.cache.redis_adapter import get_redis as _get_redis

        async def _cache_get(key: str):
            r = await _get_redis()
            return await r.get(key)

        state = "no-consume-test-state"
        nonce = "no-consume-nonce"
        _stash_state(state, nonce)

        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": state},
                # deliberately NO oauth_bind cookie
            )
        assert resp.status_code == 400

        remaining = _asyncio.get_event_loop().run_until_complete(_cache_get(f"oauth_state:{state}"))
        assert remaining is not None, "state was consumed despite missing cookie — DoS vector present"

        # Legitimate call (correct cookie) must still pass the CSRF guard.
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp2 = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": state},
                cookies={"oauth_bind": nonce},
            )
        assert resp2.status_code == 502, "legitimate flow blocked after no-cookie rejection"

    def test_wrong_cookie_does_not_consume_state(self, client):
        """A request with a wrong (but present) oauth_bind cookie must be rejected
        WITHOUT consuming the state — so the legitimate browser can still complete
        its callback.  This prevents a DoS by an attacker who knows the state URL
        and guesses/invents a random cookie value."""
        import asyncio as _asyncio
        from app.core.cache.redis_adapter import get_redis as _get_redis

        async def _cache_get(key: str):
            r = await _get_redis()
            return await r.get(key)

        state = "wrong-cookie-no-consume"
        real_nonce = "real-browser-nonce"
        _stash_state(state, real_nonce)

        # Attacker calls with wrong cookie — must 400 and leave state intact.
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"):
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": state},
                cookies={"oauth_bind": "attacker-wrong-nonce"},
            )
        assert resp.status_code == 400

        remaining = _asyncio.get_event_loop().run_until_complete(_cache_get(f"oauth_state:{state}"))
        assert remaining is not None, "state consumed by wrong-cookie request — DoS vector present"

        # Legitimate browser (correct cookie) still completes the CSRF check.
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             patch("app.routers.auth_users._httpx.AsyncClient",
                   return_value=_UnreachableProviderClient()):
            resp2 = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": state},
                cookies={"oauth_bind": real_nonce},
            )
        assert resp2.status_code == 502, "legitimate flow blocked after wrong-cookie rejection"

    def test_concurrent_callbacks_only_first_succeeds(self, client):
        """Two simultaneous callbacks with the same valid state+cookie: exactly one
        must succeed (reach the provider), the other must get 400 (replay guard)."""
        import asyncio as _asyncio
        from httpx import AsyncClient as _AClient
        from app.core.cache.redis_adapter import get_redis as _get_redis

        state = "concurrent-state"
        nonce = "concurrent-nonce"

        _concurrent_app = _make_app()

        async def _run():
            # Stash state inside the coroutine to avoid nested event-loop calls.
            r = await _get_redis()
            await r.set(f"oauth_state:{state}", nonce, ttl=600)

            # Two separate clients so their cookie jars don't share state.
            import httpx as _httpx_mod
            _transport = _httpx_mod.ASGITransport(app=_concurrent_app)
            async with _AClient(transport=_transport, base_url="http://test") as c1, \
                       _AClient(transport=_transport, base_url="http://test") as c2:
                c1.cookies.set("oauth_bind", nonce)
                c2.cookies.set("oauth_bind", nonce)
                with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
                     patch("app.routers.auth_users._httpx.AsyncClient",
                           return_value=_UnreachableProviderClient()):
                    r1, r2 = await _asyncio.gather(
                        c1.get("/api/auth/google/callback",
                               params={"code": "auth-code", "state": state}),
                        c2.get("/api/auth/google/callback",
                               params={"code": "auth-code", "state": state}),
                    )
            return [r1.status_code, r2.status_code]

        # Use a fresh loop — same pattern as _run_sync — to avoid nesting.
        loop = _asyncio.new_event_loop()
        try:
            statuses = loop.run_until_complete(_run())
        finally:
            loop.close()

        # Exactly one reaches the provider (502) and the other is rejected (400).
        assert sorted(statuses) == [400, 502], (
            f"Expected [400, 502] but got {sorted(statuses)} — "
            "either replay protection failed or both were blocked"
        )


# ── Cache failure → 503 (fail-safe) ──────────────────────────────────────────


class TestOAuthCacheFailureSafety:
    """Cache unavailability must produce 503 at both the start and callback
    endpoints — never fail-open and never leak an unhandled 500."""

    def _raise_on_get_redis(self):
        from unittest.mock import AsyncMock as _AM
        m = _AM(side_effect=RuntimeError("redis down"))
        return patch("app.core.cache.redis_adapter.get_redis", m)

    def test_google_start_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get("/api/auth/google", follow_redirects=False)
        assert resp.status_code == 503

    def test_microsoft_start_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get("/api/auth/microsoft", follow_redirects=False)
        assert resp.status_code == 503

    def test_github_start_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get("/api/auth/github", follow_redirects=False)
        assert resp.status_code == 503

    def test_google_callback_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._GOOGLE_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get(
                "/api/auth/google/callback",
                params={"code": "auth-code", "state": "any-state"},
                cookies={"oauth_bind": "any-nonce"},
            )
        assert resp.status_code == 503

    def test_microsoft_callback_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._MICROSOFT_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get(
                "/api/auth/microsoft/callback",
                params={"code": "auth-code", "state": "any-state"},
                cookies={"oauth_bind": "any-nonce"},
            )
        assert resp.status_code == 503

    def test_github_callback_503s_on_cache_failure(self, client):
        with patch("app.routers.auth_users._GITHUB_CLIENT_ID", "fake-id"), \
             self._raise_on_get_redis():
            resp = client.get(
                "/api/auth/github/callback",
                params={"code": "auth-code", "state": "any-state"},
                cookies={"oauth_bind": "any-nonce"},
            )
        assert resp.status_code == 503
