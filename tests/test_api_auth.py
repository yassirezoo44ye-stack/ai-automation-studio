"""
HTTP-level integration tests for /api/auth/* endpoints.

Uses FastAPI's TestClient with a mocked DB pool so no live Postgres is needed.
Covers: registration, login, token refresh, /me, 401 on missing/bad token,
rate-limit headers, and input validation.
"""
from __future__ import annotations

import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=user_row)
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
        from fastapi import HTTPException
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
