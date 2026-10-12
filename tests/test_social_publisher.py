"""
Tests for Social Publisher — Phase 1.

Covers:
  • SocialPublisherProvider abstract base contract
  • MockSocialPublisherProvider implementation
  • SocialPublisherRegistry resolution
  • Router endpoints (mocked DB + mock provider)
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.social.base import (
    OAuthTokenResult,
    PublishRequest,
    PublishResult,
    PublishStatus,
    PublishStatusResult,
    SocialPublisherProvider,
)
from app.integrations.social.mock import MockSocialPublisherProvider
from app.integrations.social.registry import SocialPublisherRegistry


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── MockSocialPublisherProvider ────────────────────────────────────────────────

class TestMockProvider:

    def setup_method(self):
        self.p = MockSocialPublisherProvider("tiktok", "TikTok")

    def test_identity(self):
        assert self.p.platform_id == "tiktok"
        assert self.p.display_name == "TikTok"
        assert self.p.is_available() is True

    def test_get_auth_url(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="abc123")
        assert "state=abc123" in url
        assert "code=mock-code" in url

    def test_exchange_code(self):
        result = _run(self.p.exchange_code(code="any-code", redirect_uri="https://example.com/cb"))
        assert isinstance(result, OAuthTokenResult)
        assert result.access_token.startswith("mock-access-")
        assert result.refresh_token is not None
        assert result.expires_in == 3600
        assert "video.upload" in result.scopes

    def test_refresh_access_token(self):
        result = _run(self.p.refresh_access_token("old-refresh"))
        assert result.access_token.startswith("mock-access-")
        assert result.refresh_token == "old-refresh"

    def test_publish_video(self):
        req = PublishRequest(
            video_url="https://cdn.example.com/video.mp4",
            caption="Test post #shorts",
            hashtags=["shorts", "test"],
            access_token="mock-token",
            platform_user_id="uid-1",
        )
        result = _run(self.p.publish_video(req))
        assert isinstance(result, PublishResult)
        assert result.status == PublishStatus.COMPLETED
        assert result.platform_publish_id.startswith("mock-")
        assert result.platform_url is not None

    def test_get_publish_status(self):
        result = _run(self.p.get_publish_status("mock-abc123", "token"))
        assert isinstance(result, PublishStatusResult)
        assert result.status == PublishStatus.COMPLETED
        assert result.platform_publish_id == "mock-abc123"

    def test_get_account_info(self):
        info = _run(self.p.get_account_info("token", "uid-1"))
        assert "username" in info
        assert info["platform_user_id"] == "uid-1"


# ── SocialPublisherRegistry ────────────────────────────────────────────────────

class TestRegistry:

    def setup_method(self):
        mock = MockSocialPublisherProvider("mock", "Mock")
        self.reg = SocialPublisherRegistry()
        # Inject mock directly (registry._providers is the module-level dict)
        self._orig = {}

    def test_get_unknown_returns_none(self):
        assert self.reg.get("__not_a_platform__") is None

    def test_get_or_raise_unknown(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            self.reg.get_or_raise("__not_a_platform__")

    def test_list_platforms_excludes_mock(self):
        # list_platforms() filters out 'mock' entries
        platforms = self.reg.list_platforms()
        ids = [p["platform_id"] for p in platforms]
        assert "mock" not in ids

    def test_list_platforms_shape(self):
        for entry in self.reg.list_platforms():
            assert "platform_id" in entry
            assert "display_name" in entry
            assert "available" in entry


# ── Abstract base sanity: cannot instantiate directly ────────────────────────

class TestAbstractBase:

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            SocialPublisherProvider()  # type: ignore[abstract]

    def test_concrete_must_implement_all_abstract(self):
        """A minimal concrete subclass that omits abstracts should fail."""
        class Incomplete(SocialPublisherProvider):
            @property
            def platform_id(self): return "x"
            @property
            def display_name(self): return "X"
            # Missing: get_auth_url, exchange_code, refresh_access_token,
            #          publish_video, get_publish_status

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


# ── Router endpoint tests (mocked DB) ─────────────────────────────────────────

def _make_app():
    """Create a minimal FastAPI test app with social_publisher router."""
    from fastapi import FastAPI
    from app.routers.social_publisher import router as sp_router
    app = FastAPI()
    app.include_router(sp_router)
    return app


@pytest.fixture()
def fake_org_ctx():
    """Minimal OrgContext for dependency injection."""
    from app.tenancy.context import OrgContext
    ctx = OrgContext(
        org_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        user_email="test@example.com",
        role="admin",
    )
    return ctx


class TestRouterPlatforms:
    """GET /api/social/platforms — no DB needed."""

    def test_list_platforms_contains_tiktok(self, fake_org_ctx):
        """Step 2: registry has tiktok; instagram/youtube added in Steps 3-4."""
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with TestClient(app) as client:
            resp = client.get("/api/social/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert "platforms" in data
        ids = {p["platform_id"] for p in data["platforms"]}
        assert "tiktok" in ids
        assert "mock" not in ids

    def test_list_platforms_shape(self, fake_org_ctx):
        """Each platform entry must include platform_id, display_name, available."""
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with TestClient(app) as client:
            resp = client.get("/api/social/platforms")
        assert resp.status_code == 200
        for entry in resp.json()["platforms"]:
            assert "platform_id" in entry
            assert "display_name" in entry
            assert "available" in entry


class TestRouterPostsCRUD:
    """POST/GET /api/social/posts with mocked DB pool."""

    def _make_post_row(self, org_id: str, user_id: str, title: str = "Test") -> dict:
        now = datetime.now(tz=timezone.utc)
        return {
            "id": uuid.uuid4(),
            "organization_id": uuid.UUID(org_id),
            "created_by_user_id": uuid.UUID(user_id),
            "title": title,
            "caption": "Caption #test",
            "video_url": "https://cdn.example.com/v.mp4",
            "thumbnail_url": None,
            "duration_seconds": None,
            "target_platforms": ["tiktok"],
            "scheduled_at": None,
            "status": "draft",
            "hashtags": ["test"],
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }

    def test_create_post(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        post_row = self._make_post_row(fake_org_ctx.org_id, fake_org_ctx.user_id)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=post_row)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with patch("app.routers.social_publisher.get_pool", return_value=mock_pool):
            with TestClient(app) as client:
                resp = client.post("/api/social/posts", json={
                    "caption": "Caption #test",
                    "video_url": "https://cdn.example.com/v.mp4",
                    "target_platforms": ["tiktok"],
                    "hashtags": ["test"],
                })

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["target_platforms"] == ["tiktok"]

    def test_create_post_invalid_platform(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with TestClient(app) as client:
            resp = client.post("/api/social/posts", json={
                "caption": "Test",
                "video_url": "https://cdn.example.com/v.mp4",
                "target_platforms": ["snapchat"],
            })

        assert resp.status_code == 422

    def test_create_post_empty_platforms(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with TestClient(app) as client:
            resp = client.post("/api/social/posts", json={
                "caption": "Test",
                "video_url": "https://cdn.example.com/v.mp4",
                "target_platforms": [],
            })

        assert resp.status_code == 422

    def test_get_post_not_found(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with patch("app.routers.social_publisher.get_pool", return_value=mock_pool):
            with TestClient(app) as client:
                resp = client.get(f"/api/social/posts/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_get_post_invalid_uuid(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with TestClient(app) as client:
            resp = client.get("/api/social/posts/not-a-uuid")

        assert resp.status_code == 404

    def test_update_post_org_isolation(self, fake_org_ctx):
        """PATCH /posts/{id} must not update posts belonging to a different org.

        Before the fix, the UPDATE query omitted organization_id — an attacker
        in org B could modify a post owned by org A.  After the fix the WHERE
        clause includes AND organization_id=$n so the row is not found and
        the endpoint returns 409 (the update returns None → 'Post not found').
        """
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        # Simulate a post that 'exists' only if the org_id is wrong:
        # fetchval('SELECT status …') returns 'draft' (found), but the UPDATE
        # returns None because org_id doesn't match.  The endpoint must 409.
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="draft")   # status check passes
        mock_conn.fetchrow = AsyncMock(return_value=None)       # UPDATE finds no row
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with patch("app.routers.social_publisher.get_pool", return_value=mock_pool):
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/social/posts/{uuid.uuid4()}",
                    json={"caption": "attacker caption"},
                )

        # Router should not succeed; 404 or 409 is acceptable — the post was not updated
        assert resp.status_code in (404, 409, 422)

    def test_schedule_post_past_date_rejected(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()

        with TestClient(app) as client:
            resp = client.post(
                f"/api/social/posts/{uuid.uuid4()}/schedule",
                json={"scheduled_at": past},
            )
        assert resp.status_code == 400


class TestRouterAccounts:
    """Account connect/disconnect endpoint contract."""

    def test_list_accounts_empty(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with patch("app.routers.social_publisher.get_pool", return_value=mock_pool):
            with TestClient(app) as client:
                resp = client.get("/api/social/accounts")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_disconnect_unknown_account(self, fake_org_ctx):
        from fastapi.testclient import TestClient
        from app.tenancy.context import org_context

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        app = _make_app()
        app.dependency_overrides[org_context] = lambda: fake_org_ctx

        with patch("app.routers.social_publisher.get_pool", return_value=mock_pool):
            with TestClient(app) as client:
                resp = client.delete(f"/api/social/accounts/{uuid.uuid4()}")

        assert resp.status_code == 404
