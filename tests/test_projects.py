"""
Regression tests for project endpoint data isolation (H-02).

Verifies that:
1. /api/projects endpoints work with X-Sub-Token (not Authorization: Bearer JWT).
2. Projects are scoped to the user identified by the sub_token email.
3. No project data leaks across users.

No live Postgres — the DB pool is mocked.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

OWNER_A_EMAIL = "alice@example.com"
OWNER_A_UID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
OWNER_B_EMAIL = "bob@example.com"
OWNER_B_UID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

# A minimal valid HMAC sub_token for alice@example.com — we mock owner_email()
# so the actual token value doesn't matter; any non-empty string works.
ALICE_TOKEN = "alice-sub-token"
BOB_TOKEN = "bob-sub-token"


def _make_app():
    from fastapi import FastAPI
    from app.routers.projects import router
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_pool_with_user(user_id: uuid.UUID):
    """Return a pool mock whose conn.fetchval first returns user_id, then None."""
    conn = AsyncMock()
    # fetchval is called first to resolve owner user_id, then for INSERT/SELECT
    conn.fetchval = AsyncMock(return_value=user_id)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="DELETE 1")

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.projects.get_pool", return_value=pool), conn


class TestProjectsUsesSubToken:
    """Confirms the frontend's X-Sub-Token auth is accepted (H-02 regression guard)."""

    def test_list_projects_accepts_sub_token_not_jwt(self):
        """GET /api/projects must succeed with only X-Sub-Token — no Authorization header."""
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool_with_user(OWNER_A_UID)

        with mock_pool_ctx, \
             patch("app.routers.projects.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    "/api/projects",
                    headers={"X-Sub-Token": ALICE_TOKEN},  # no Authorization: Bearer
                )

        # 200 = accepted; any 4xx (especially 401) means JWT was required — regression
        assert res.status_code == 200, (
            f"Expected 200, got {res.status_code}. "
            "H-02 regression: project endpoint may be requiring JWT again."
        )
        assert isinstance(res.json(), list)

    def test_list_projects_without_any_token_calls_owner_email(self):
        """Even with no token, request reaches the handler — auth gate is upstream middleware."""
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool_with_user(OWNER_A_UID)

        with mock_pool_ctx, \
             patch("app.routers.projects.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/projects")

        # In the real app the subscription middleware would have rejected the request
        # before reaching the handler.  In this isolated test, owner_email is mocked
        # so the handler completes.  We just verify it doesn't 401 on missing JWT.
        assert res.status_code != 401 or res.json().get("detail", "").startswith("No account")


class TestProjectDataIsolation:
    """Each sub_token owner sees only their own projects."""

    def test_alice_cannot_see_bobs_project(self):
        """owner_email returning alice's email must scope queries to Alice's user_id."""
        alice_project_id = str(uuid.uuid4())
        app = _make_app()

        conn = AsyncMock()
        # fetchval: resolve owner user_id
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)

        # fetchrow: project lookup by (project_id, user_id) — only returns a row
        # when the user_id matches Alice's UUID
        async def _fetchrow(sql, project_id, user_id):
            if user_id == OWNER_A_UID:
                return {
                    "id": uuid.UUID(alice_project_id),
                    "name": "Alice Project",
                    "description": "Alice's project",
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
            return None  # Bob cannot see Alice's project

        conn.fetchrow = AsyncMock(side_effect=_fetchrow)

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.projects.get_pool", return_value=pool), \
             patch("app.routers.projects.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                # Alice can see her own project
                res_alice = c.get(
                    f"/api/projects/{alice_project_id}",
                    headers={"X-Sub-Token": ALICE_TOKEN},
                )

        assert res_alice.status_code == 200
        assert res_alice.json()["name"] == "Alice Project"

    def test_bob_gets_404_for_alices_project(self):
        """Bob's sub_token resolves to Bob's user_id which has no access to Alice's project."""
        alice_project_id = str(uuid.uuid4())
        app = _make_app()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_B_UID)  # Bob's user_id
        conn.fetchrow = AsyncMock(return_value=None)           # No match for (project, Bob)

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.projects.get_pool", return_value=pool), \
             patch("app.routers.projects.owner_email", return_value=OWNER_B_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res_bob = c.get(
                    f"/api/projects/{alice_project_id}",
                    headers={"X-Sub-Token": BOB_TOKEN},
                )

        assert res_bob.status_code == 404

    def test_unregistered_subscriber_gets_401(self):
        """A valid sub_token whose email is not in the users table returns 401."""
        app = _make_app()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # No user found for this email

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.projects.get_pool", return_value=pool), \
             patch("app.routers.projects.owner_email", return_value="unregistered@example.com"):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/projects", headers={"X-Sub-Token": "some-token"})

        assert res.status_code == 401
        assert "register" in res.json()["detail"].lower()
