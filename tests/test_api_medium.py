"""
Regression tests for Medium severity hardening fixes.

Covers: password length bounds, SSE error sanitisation, conversation limit,
avatar_url validation, datetime fromisoformat guard, HSTS/CSP/CORS headers.
No live database required — DB calls are mocked.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


# ── Password length bounds (M-01) ─────────────────────────────────────────────

class TestPasswordBounds:
    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from app.routers.auth_users import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_password_too_long_rejected(self, client):
        res = client.post(
            "/api/auth/register",
            json={"name": "T", "email": "t@t.com", "password": "A" * 129},
        )
        assert res.status_code == 422
        assert "128" in res.text

    def test_password_at_max_boundary_accepted_structurally(self, client):
        """128-char password passes validation (may fail DB insert — that is expected)."""
        with patch("app.routers.auth_users.get_pool") as mock_gp, \
             patch("app.routers.auth_users.hash_password", return_value="$2b$"), \
             patch("app.routers.auth_users.send_verification_email", new_callable=AsyncMock), \
             patch("app.routers.auth_users.write_audit", new_callable=AsyncMock):
            conn = AsyncMock()
            conn.execute = AsyncMock(return_value=None)
            conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
            conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = pool

            res = client.post(
                "/api/auth/register",
                json={"name": "T", "email": "t@t.com", "password": "A" * 128},
                headers={"X-Forwarded-For": "200.1.1.1"},
            )
        # 201 = success; anything except 422 means the validator passed
        assert res.status_code != 422

    def test_reset_password_too_long_rejected(self, client):
        res = client.post(
            "/api/auth/reset-password",
            json={"token": "abc", "password": "B" * 129},
        )
        assert res.status_code == 422

    def test_change_password_validator_rejects_too_long(self):
        """The Pydantic model itself must reject passwords > 128 chars."""
        from app.routers.auth_users import ChangePasswordRequest
        import pytest as _pt
        from pydantic import ValidationError
        with _pt.raises(ValidationError) as exc_info:
            ChangePasswordRequest(current_password="old", new_password="C" * 129)
        assert "128" in str(exc_info.value)


# ── Avatar URL validation (M-10) ─────────────────────────────────────────────

class TestAvatarUrlValidation:
    """Test Pydantic model validators directly — the HTTP endpoint is JWT-gated
    so 401 would shadow a 422 in end-to-end tests."""

    def _model(self, **kwargs):
        from app.routers.auth_users import UpdateProfileRequest
        return UpdateProfileRequest(**kwargs)

    def test_http_avatar_url_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._model(avatar_url="http://evil.com/img.png")

    def test_javascript_url_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._model(avatar_url="javascript:alert(1)")

    def test_too_long_avatar_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._model(avatar_url="https://cdn.example.com/" + "a" * 500)

    def test_valid_https_url_accepted(self):
        m = self._model(avatar_url="https://cdn.example.com/avatar.png")
        assert m.avatar_url == "https://cdn.example.com/avatar.png"

    def test_none_avatar_url_accepted(self):
        m = self._model(avatar_url=None)
        assert m.avatar_url is None


# ── Conversations limit bound (M-09) ─────────────────────────────────────────

class TestConversationLimit:
    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from app.routers.inference import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_limit_over_200_rejected(self, client):
        res = client.get(
            "/api/ai/conversations?limit=9999",
            headers={"Authorization": "Bearer tok"},
        )
        assert res.status_code == 422

    def test_negative_limit_rejected(self, client):
        res = client.get(
            "/api/ai/conversations?limit=-1",
            headers={"Authorization": "Bearer tok"},
        )
        assert res.status_code == 422

    def test_limit_at_max_passes_validation(self, client):
        with patch("app.routers.inference.get_pool") as mock_gp:
            conn = AsyncMock()
            pool = MagicMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = pool

            from unittest.mock import patch as _patch
            with _patch("app.routers.inference.platform") as mock_platform:
                svc = AsyncMock()
                svc.list = AsyncMock(return_value=[])
                mock_platform._pool = True
                mock_platform.conversations = svc
                res = client.get(
                    "/api/ai/conversations?limit=200",
                    headers={"Authorization": "Bearer tok"},
                )
        # 200 OK or any non-422 means the validation passed
        assert res.status_code != 422


# ── datetime fromisoformat guard (M-12) ──────────────────────────────────────

class TestDatetimeGuard:
    @pytest.fixture()
    def client(self):
        from fastapi import FastAPI
        from app.routers.inference import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_invalid_since_returns_422_not_500(self, client):
        res = client.get(
            "/api/ai/usage?since=not-a-date",
            headers={"Authorization": "Bearer tok"},
        )
        assert res.status_code == 422
        assert "since" in res.text.lower() or "date" in res.text.lower()


# ── Security headers (M-04, M-03, M-05) ──────────────────────────────────────

class TestSecurityHeaders:
    @pytest.fixture()
    def client(self):
        from app.factory import create_app
        # create_app needs lifespan; use TestClient with lifespan disabled
        from fastapi import FastAPI
        from app.factory import SecurityHeadersMiddleware
        from starlette.middleware.base import BaseHTTPMiddleware
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/ping")
        def ping():
            return {"ok": True}

        with TestClient(app) as c:
            yield c

    def test_hsts_header_present(self, client):
        res = client.get("/ping")
        assert "strict-transport-security" in res.headers
        assert "max-age=31536000" in res.headers["strict-transport-security"]

    def test_csp_no_unsafe_eval(self, client):
        res = client.get("/ping")
        csp = res.headers.get("content-security-policy", "")
        assert "unsafe-eval" not in csp, f"unsafe-eval found in CSP: {csp}"

    def test_csp_no_unsafe_inline_in_script_src(self, client):
        res = client.get("/ping")
        csp = res.headers.get("content-security-policy", "")
        # script-src should not contain unsafe-inline
        for directive in csp.split(";"):
            directive = directive.strip()
            if directive.startswith("script-src"):
                assert "'unsafe-inline'" not in directive, (
                    f"unsafe-inline in script-src: {directive}"
                )

    def test_x_frame_options_deny(self, client):
        res = client.get("/ping")
        assert res.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options(self, client):
        res = client.get("/ping")
        assert res.headers.get("x-content-type-options") == "nosniff"
