"""
Teams/Organizations chat tests — service query scoping, room resolution
for the WS transport, and the REST router's auth/room-existence gates.

No live Postgres — pool/conn are mocked (same pattern as
tests/test_notifications.py / tests/test_presence.py).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ── ChatService ──────────────────────────────────────────────────────────────

class TestChatServiceCreateMessage:
    def test_rejects_empty_body(self):
        from app.core.chat.service import ChatService
        svc = ChatService(_mock_pool(AsyncMock()))
        with pytest.raises(ValueError):
            run(svc.create_message(
                organization_id=str(uuid.uuid4()), team_id=None,
                user_id=str(uuid.uuid4()), body="   ",
            ))

    def test_rejects_oversized_body(self):
        from app.core.chat.service import ChatService, MAX_BODY_LENGTH
        svc = ChatService(_mock_pool(AsyncMock()))
        with pytest.raises(ValueError):
            run(svc.create_message(
                organization_id=str(uuid.uuid4()), team_id=None,
                user_id=str(uuid.uuid4()), body="x" * (MAX_BODY_LENGTH + 1),
            ))

    def test_strips_whitespace_before_insert(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        row = {
            "id": uuid.uuid4(), "organization_id": uuid.uuid4(), "team_id": None,
            "user_id": uuid.uuid4(), "body": "hello", "created_at": None, "edited_at": None,
        }
        conn.fetchrow = AsyncMock(return_value=row)
        svc = ChatService(_mock_pool(conn))

        run(svc.create_message(
            organization_id=str(uuid.uuid4()), team_id=None,
            user_id=str(uuid.uuid4()), body="  hello  ",
        ))

        args = conn.fetchrow.call_args.args
        assert args[-1] == "hello"  # body is the last bound param

    def test_general_room_passes_null_team_id(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": uuid.uuid4(), "organization_id": uuid.uuid4(), "team_id": None,
            "user_id": uuid.uuid4(), "body": "hi", "created_at": None, "edited_at": None,
        })
        svc = ChatService(_mock_pool(conn))

        run(svc.create_message(
            organization_id=str(uuid.uuid4()), team_id=None,
            user_id=str(uuid.uuid4()), body="hi",
        ))

        # team_id param (3rd bound param, i.e. args[2] after the SQL string)
        # must be None, not the string "None".
        assert conn.fetchrow.call_args.args[2] is None


class TestChatServiceListMessages:
    def test_general_room_filters_team_id_is_null(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = ChatService(_mock_pool(conn))

        run(svc.list_messages(organization_id=str(uuid.uuid4()), team_id=None))

        sql = conn.fetch.call_args.args[0]
        assert "cm.team_id IS NULL" in sql

    def test_team_room_filters_by_team_id_param(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = ChatService(_mock_pool(conn))

        team_id = str(uuid.uuid4())
        run(svc.list_messages(organization_id=str(uuid.uuid4()), team_id=team_id))

        sql, *params = conn.fetch.call_args.args
        assert "cm.team_id=$2" in sql
        assert uuid.UUID(team_id) in params

    def test_excludes_soft_deleted_messages(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = ChatService(_mock_pool(conn))

        run(svc.list_messages(organization_id=str(uuid.uuid4()), team_id=None))

        sql = conn.fetch.call_args.args[0]
        assert "cm.deleted_at IS NULL" in sql

    def test_limit_is_clamped_to_100(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = ChatService(_mock_pool(conn))

        run(svc.list_messages(organization_id=str(uuid.uuid4()), team_id=None, limit=9999))

        sql, *params = conn.fetch.call_args.args
        assert params[-1] == 100

    def test_before_cursor_adds_created_at_subquery(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = ChatService(_mock_pool(conn))

        before_id = str(uuid.uuid4())
        run(svc.list_messages(organization_id=str(uuid.uuid4()), team_id=None, before=before_id))

        sql, *params = conn.fetch.call_args.args
        assert "cm.created_at < (SELECT created_at FROM chat_messages WHERE id=" in sql
        assert uuid.UUID(before_id) in params


class TestChatServiceDeleteMessage:
    def test_delete_scoped_to_owner(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")
        svc = ChatService(_mock_pool(conn))

        ok = run(svc.delete_message(message_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())))

        assert ok is False
        sql = conn.execute.call_args.args[0]
        assert "user_id=$2" in sql

    def test_delete_returns_true_when_row_matched(self):
        from app.core.chat.service import ChatService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        svc = ChatService(_mock_pool(conn))

        ok = run(svc.delete_message(message_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())))
        assert ok is True


# ── WS room resolution ───────────────────────────────────────────────────────

class TestResolveChatRoom:
    def test_org_room_returns_the_org_id_directly(self):
        from app.routers.ws import _resolve_chat_room
        org_id = str(uuid.uuid4())
        assert run(_resolve_chat_room(f"org:{org_id}")) == org_id

    def test_malformed_org_id_returns_none(self):
        from app.routers.ws import _resolve_chat_room
        assert run(_resolve_chat_room("org:not-a-uuid")) is None

    def test_unknown_room_prefix_returns_none(self):
        from app.routers.ws import _resolve_chat_room
        assert run(_resolve_chat_room("bogus:123")) is None

    def test_team_room_looks_up_owning_org(self):
        from app.routers.ws import _resolve_chat_room

        team_id = str(uuid.uuid4())
        org_id = uuid.uuid4()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=org_id)
        pool = _mock_pool(conn)

        with patch("app.core.db.get_pool", return_value=pool):
            result = run(_resolve_chat_room(f"team:{team_id}"))

        assert result == str(org_id)

    def test_team_room_for_deleted_or_missing_team_returns_none(self):
        from app.routers.ws import _resolve_chat_room

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        pool = _mock_pool(conn)

        with patch("app.core.db.get_pool", return_value=pool):
            result = run(_resolve_chat_room(f"team:{uuid.uuid4()}"))

        assert result is None

    def test_malformed_team_id_returns_none(self):
        from app.routers.ws import _resolve_chat_room
        assert run(_resolve_chat_room("team:not-a-uuid")) is None


# ── Router: REST surface ────────────────────────────────────────────────────

@pytest.fixture()
def chat_client():
    from fastapi import FastAPI
    from app.routers.team_chat import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestTeamChatRouter:
    def test_list_general_messages_requires_authentication(self, chat_client):
        res = chat_client.get(f"/api/orgs/{uuid.uuid4()}/chat/messages")
        assert res.status_code == 401

    def test_post_general_message_requires_authentication(self, chat_client):
        res = chat_client.post(f"/api/orgs/{uuid.uuid4()}/chat/messages", json={"body": "hi"})
        assert res.status_code == 401

    def test_post_general_message_broadcasts_after_persisting(self):
        from app.routers.team_chat import post_general_message
        from app.tenancy import OrgContext

        ctx = OrgContext(org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                          user_email="a@example.com", role="developer")
        fake_svc = MagicMock()
        stored = {"id": "m1", "organization_id": ctx.org_id, "team_id": None,
                  "user_id": ctx.user_id, "body": "hi there"}
        fake_svc.create_message = AsyncMock(return_value=stored)
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        from app.routers.team_chat import PostMessageRequest
        with patch("app.routers.team_chat.get_chat_service", return_value=fake_svc), \
             patch("app.routers.ws.manager", fake_ws):
            result = run(post_general_message(PostMessageRequest(body="hi there"), ctx=ctx))

        assert result == stored
        fake_ws.broadcast.assert_awaited_once_with(f"chat:org:{ctx.org_id}", stored)

    def test_post_team_message_404s_when_team_not_in_org(self):
        from app.routers.team_chat import post_team_message, PostMessageRequest
        from app.tenancy import OrgContext
        from fastapi import HTTPException

        ctx = OrgContext(org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                          user_email="a@example.com", role="developer")
        fake_tenancy = MagicMock()
        fake_tenancy.get_team = AsyncMock(return_value=None)

        with patch("app.routers.team_chat.get_tenancy_service", return_value=fake_tenancy):
            with pytest.raises(HTTPException) as exc_info:
                run(post_team_message(str(uuid.uuid4()), PostMessageRequest(body="hi"), ctx=ctx))

        assert exc_info.value.status_code == 404

    def test_delete_message_404s_when_not_owner_or_missing(self):
        from app.routers.team_chat import delete_message
        from app.tenancy import OrgContext
        from fastapi import HTTPException

        ctx = OrgContext(org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                          user_email="a@example.com", role="developer")
        fake_svc = MagicMock()
        fake_svc.delete_message = AsyncMock(return_value=False)

        with patch("app.routers.team_chat.get_chat_service", return_value=fake_svc):
            with pytest.raises(HTTPException) as exc_info:
                run(delete_message(str(uuid.uuid4()), ctx=ctx))

        assert exc_info.value.status_code == 404

    def test_delete_message_succeeds_for_owner(self):
        from app.routers.team_chat import delete_message
        from app.tenancy import OrgContext

        ctx = OrgContext(org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                          user_email="a@example.com", role="developer")
        fake_svc = MagicMock()
        fake_svc.delete_message = AsyncMock(return_value=True)

        with patch("app.routers.team_chat.get_chat_service", return_value=fake_svc):
            run(delete_message(str(uuid.uuid4()), ctx=ctx))  # must not raise
