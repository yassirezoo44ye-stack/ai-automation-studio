"""
Regression tests for /api/conversations, /api/search, and
/api/export/conversations cross-tenant data isolation (H-03).

Found during manual QA: an account with 0 conversations of its own saw
another account's real chat history (including message content) on the
AI/Chat page. Root cause was two-fold:

1. resolve_project_id() mapped the frontend's "New Chat" default
   (project_id="demo") to ONE fixed global UUID for every user, so
   everyone's default project was the same database row.
2. list_conversations/get_messages/delete_conversation/search/
   export_conversation ran with zero ownership checks — any conv_id
   worked for any caller.

Fixed by routing every query through resolve_project_id(conn, id, uid)
(find-or-create the caller's OWN demo project; verify ownership of any
explicit id) and joining conversations->projects.user_id everywhere.

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
    from app.routers.chat import router
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_pool(conn: AsyncMock):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("app.routers.chat.get_pool", return_value=pool)


class TestConversationsIsScoped:
    def test_list_conversations_without_project_id_scopes_to_owner(self):
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)  # owner_user_id lookup
        conn.fetch = AsyncMock(return_value=[])

        with _mock_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/conversations", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        sql, *params = conn.fetch.call_args_list[0].args
        assert "p.user_id" in sql
        assert OWNER_A_UID in params

    def test_get_messages_for_foreign_conversation_returns_404(self):
        """A conv_id belonging to another user must not leak its messages."""
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[OWNER_A_UID, None])  # owner uid, then ownership check fails
        conn.fetch = AsyncMock(return_value=[{"id": uuid.uuid4(), "role": "user",
                                               "content": "secret", "created_at": __import__("datetime").datetime.now()}])

        foreign_conv_id = str(uuid.uuid4())
        with _mock_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/conversations/{foreign_conv_id}/messages",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
        # messages fetch must never have been reached
        conn.fetch.assert_not_called()

    def test_delete_conversation_not_owned_returns_404_and_does_not_delete(self):
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.execute = AsyncMock(return_value="DELETE 0")  # WHERE matched nothing

        foreign_conv_id = str(uuid.uuid4())
        with _mock_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.delete(
                    f"/api/conversations/{foreign_conv_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
        sql = conn.execute.call_args_list[0].args[0]
        assert "p.user_id" in sql

    def test_search_scopes_conversations_and_messages_to_owner(self):
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.fetch = AsyncMock(return_value=[])

        with _mock_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/search?q=hello", headers={"X-Sub-Token": "alice-token"})

        assert res.status_code == 200
        assert conn.fetch.call_count == 2
        for call in conn.fetch.call_args_list:
            sql, *params = call.args
            assert "p.user_id" in sql
            assert OWNER_A_UID in params

    def test_export_foreign_conversation_returns_404(self):
        app = _make_app()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=OWNER_A_UID)
        conn.fetchrow = AsyncMock(return_value=None)  # ownership JOIN finds nothing

        foreign_conv_id = str(uuid.uuid4())
        with _mock_pool(conn), patch("app.core.auth.owner_email", return_value=OWNER_A_EMAIL):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get(
                    f"/api/export/conversations/{foreign_conv_id}",
                    headers={"X-Sub-Token": "alice-token"},
                )

        assert res.status_code == 404
