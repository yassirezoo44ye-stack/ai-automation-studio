"""
Regression tests for /api/stats, /api/stats/timeseries, /api/agent-runs, and
/api/usage-logs cross-tenant data isolation.

Found during manual QA: these four endpoints ran completely unscoped SQL
(SELECT COUNT(*) FROM conversations, SELECT * FROM usage_logs ORDER BY ...
with no WHERE clause at all) — any authenticated user's dashboard showed
every user's conversation/message/build counts and activity feed. Fixed by
routing every query through the same owner_user_id() resolution used by
/api/projects (H-02). These tests assert the resolved user_id is actually
bound into every query, not just that a 200 comes back.

No live Postgres — the DB pool is mocked.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

OWNER_A_EMAIL = "alice@example.com"
OWNER_A_UID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


def _make_app():
    from fastapi import FastAPI
    from app.routers.stats import router
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_pool():
    """fetchval always resolves the owner lookup to OWNER_A_UID; every other
    fetchval/fetch call is recorded so tests can assert the uid was bound."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
    conn.fetch = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.stats.get_pool", return_value=pool), conn


class TestStatsIsScoped:
    def test_get_stats_scopes_every_query_to_the_owner(self):
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool()

        with mock_pool_ctx, patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/stats", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200

        # First fetchval call resolves owner_user_id; every subsequent
        # fetchval/fetch call must bind that same uid as a query parameter.
        fetchval_calls = conn.fetchval.call_args_list
        assert len(fetchval_calls) >= 4, "expected owner lookup + 3 COUNT queries"
        for call in fetchval_calls[1:]:
            sql = call.args[0]
            assert "user_id" in sql or "p.user_id" in sql, (
                f"query has no owner scoping: {sql!r}"
            )
            assert OWNER_A_UID in call.args, (
                f"resolved uid not bound as a parameter: {call.args!r}"
            )

        fetch_calls = conn.fetch.call_args_list
        assert len(fetch_calls) == 1, "expected exactly one recent_activity query"
        sql, *params = fetch_calls[0].args
        assert "user_id" in sql
        assert OWNER_A_UID in params

    def test_timeseries_scopes_both_queries_to_the_owner(self):
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool()

        with mock_pool_ctx, patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    "/api/stats/timeseries?days=7",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 200
        fetch_calls = conn.fetch.call_args_list
        assert len(fetch_calls) == 2, "expected the messages query and the builds query"
        for call in fetch_calls:
            sql, *params = call.args
            assert "user_id" in sql
            assert OWNER_A_UID in params

    def test_usage_logs_scopes_to_the_owner(self):
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool()

        with mock_pool_ctx, patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/usage-logs", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        sql, *params = conn.fetch.call_args_list[0].args
        assert "WHERE user_id=$1" in sql
        assert OWNER_A_UID in params

    def test_agent_runs_without_project_id_scopes_to_the_owner(self):
        app = _make_app()
        mock_pool_ctx, conn = _mock_pool()

        with mock_pool_ctx, patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/agent-runs", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        sql, *params = conn.fetch.call_args_list[0].args
        assert "p.user_id" in sql
        assert OWNER_A_UID in params

    def test_agent_runs_with_foreign_project_id_returns_404(self):
        """A project_id belonging to another user must not leak that user's runs."""
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[OWNER_A_UID, None])  # owner uid, then ownership check fails
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        foreign_project_id = str(uuid.uuid4())
        with patch("app.routers.stats.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/agent-runs?project_id={foreign_project_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
