"""
Presence tests — heartbeat TTL semantics, pub/sub fan-out to org-mates,
the presence REST snapshot endpoint, and the notifications-socket wiring
that doubles as the presence heartbeat transport (app/routers/ws.py).

No live Redis/Postgres — cache and pool are mocked (same pattern as
tests/test_notifications.py).
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


class _FakeRedis:
    """Minimal in-memory stand-in for RedisAdapter — enough surface for
    PresenceService (get/set/delete/mget/publish/subscribe)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = str(value)

    async def delete(self, key):
        self.store.pop(key, None)

    async def mget(self, *keys):
        return [self.store.get(k) for k in keys]

    async def publish(self, channel, message):
        self.published.append((channel, message))

    async def subscribe(self, channel, callback):
        pass


# ── PresenceService: TTL semantics ──────────────────────────────────────────────

class TestPresenceServiceTouch:
    def test_touch_from_offline_marks_online_and_publishes_change(self):
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            transitioned = run(svc.touch("user-1"))

        assert transitioned is True
        assert fake.store["presence:user-1"] is not None
        assert len(fake.published) == 1
        assert fake.published[0][0] == "presence:changes"
        assert '"online": true' in fake.published[0][1]

    def test_repeated_touch_while_online_does_not_republish(self):
        """A heartbeat every ~15s must refresh the TTL without re-firing the
        pub/sub change event on every single ping — only real transitions
        should fan out."""
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            first = run(svc.touch("user-1"))
            second = run(svc.touch("user-1"))
            third = run(svc.touch("user-1"))

        assert first is True
        assert second is False
        assert third is False
        assert len(fake.published) == 1

    def test_is_online_reflects_ttl_key_presence(self):
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            assert run(svc.is_online("user-1")) is False
            run(svc.touch("user-1"))
            assert run(svc.is_online("user-1")) is True

    def test_bulk_status_reports_each_user_independently(self):
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            run(svc.touch("online-user"))
            result = run(svc.bulk_status(["online-user", "offline-user"]))

        assert result == {"online-user": True, "offline-user": False}

    def test_bulk_status_of_empty_list_short_circuits(self):
        from app.core.presence.service import PresenceService
        svc = PresenceService()
        assert run(svc.bulk_status([])) == {}


class TestPresenceServiceMarkOffline:
    def test_mark_offline_deletes_key_and_publishes_when_was_online(self):
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            run(svc.touch("user-1"))
            run(svc.mark_offline("user-1"))

        assert "presence:user-1" not in fake.store
        assert len(fake.published) == 2  # online, then offline
        assert '"online": false' in fake.published[1][1]

    def test_mark_offline_when_already_offline_is_a_silent_noop(self):
        """No transition happened, so no change event should be published —
        otherwise a stray disconnect on an already-offline connection would
        spam org-mates with a phantom offline notice."""
        from app.core.presence.service import PresenceService

        fake = _FakeRedis()
        svc = PresenceService()
        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            run(svc.mark_offline("never-online-user"))

        assert fake.published == []


# ── Fan-out: pub/sub change -> broadcast to org-mates only ─────────────────────

class TestPresenceFanout:
    def test_fanout_broadcasts_to_every_org_mate_across_all_shared_orgs(self):
        from app.core.presence.service import PresenceService

        svc = PresenceService()
        fake_notif_svc = MagicMock()
        fake_notif_svc.org_ids_for_user = AsyncMock(return_value=["org-a", "org-b"])
        fake_notif_svc.org_member_ids = AsyncMock(
            side_effect=lambda organization_id: (
                ["user-1", "user-2"] if organization_id == "org-a" else ["user-1", "user-3"]
            )
        )
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.core.notifications.service.get_notification_service", return_value=fake_notif_svc), \
             patch("app.routers.ws.manager", fake_ws):
            run(svc._fanout_to_org_mates("user-1", True))

        # user-1 (the subject) must never be broadcast to themselves; user-2
        # and user-3 (deduped across both shared orgs) each get exactly one.
        broadcast_topics = {c.args[0] for c in fake_ws.broadcast.call_args_list}
        assert broadcast_topics == {"presence:user-2", "presence:user-3"}
        for c in fake_ws.broadcast.call_args_list:
            assert c.args[1] == {"user_id": "user-1", "online": True}

    def test_fanout_with_no_shared_orgs_broadcasts_to_nobody(self):
        from app.core.presence.service import PresenceService

        svc = PresenceService()
        fake_notif_svc = MagicMock()
        fake_notif_svc.org_ids_for_user = AsyncMock(return_value=[])
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.core.notifications.service.get_notification_service", return_value=fake_notif_svc), \
             patch("app.routers.ws.manager", fake_ws):
            run(svc._fanout_to_org_mates("lonely-user", False))

        fake_ws.broadcast.assert_not_called()

    def test_on_change_callback_swallows_malformed_payloads(self):
        """A subscribe() callback that raises would kill the Redis pub/sub
        listener task for every future message (see RedisCacheBackend._listen)
        — malformed JSON must never propagate."""
        from app.core.presence.service import PresenceService

        svc = PresenceService()
        fake = _FakeRedis()
        captured_callback = {}

        async def fake_subscribe(channel, callback):
            captured_callback["cb"] = callback

        fake.subscribe = fake_subscribe

        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            run(svc.wire_fanout())
            # Must not raise despite garbage input.
            run(captured_callback["cb"]("not json"))
            run(captured_callback["cb"]('{"user_id": "u1"}'))  # missing "online"

    def test_wire_fanout_is_idempotent(self):
        from app.core.presence.service import PresenceService

        svc = PresenceService()
        fake = _FakeRedis()
        fake.subscribe = AsyncMock()

        with patch("app.core.presence.service.get_redis", AsyncMock(return_value=fake)):
            run(svc.wire_fanout())
            run(svc.wire_fanout())

        assert fake.subscribe.await_count == 1


# ── NotificationService.org_ids_for_user ────────────────────────────────────────

def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class TestOrgIdsForUser:
    def test_queries_scoped_to_user_and_excludes_soft_deleted(self):
        from app.core.notifications.service import NotificationService

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"organization_id": uuid.UUID(int=1)}])
        svc = NotificationService(_mock_pool(conn))

        uid = str(uuid.uuid4())
        result = run(svc.org_ids_for_user(user_id=uid))

        assert result == [str(uuid.UUID(int=1))]
        sql, *params = conn.fetch.call_args.args
        assert "user_id=$1" in sql
        assert "deleted_at IS NULL" in sql
        assert uuid.UUID(uid) in params


# ── Router: GET /api/orgs/{id}/presence ─────────────────────────────────────────
#
# require_permission("resource", "action") returns a fresh closure on every
# call, so it can't be targeted via FastAPI's dependency_overrides (the key
# must be the exact object instantiated when the route was decorated at
# import time). Every other require_permission-gated endpoint in this
# codebase is tested the same way — by calling the route function directly
# with a hand-built OrgContext, bypassing the dependency-resolution layer
# rather than fighting it (see tests/test_enterprise.py's permission-matrix
# tests for the same reasoning applied to authorization itself).

@pytest.fixture()
def org_client():
    from fastapi import FastAPI
    from app.routers.organizations import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token():
    from app.core.jwt_utils import make_access_token
    return make_access_token(str(uuid.uuid4()), "user@example.com")


class TestPresenceRouter:
    def test_presence_endpoint_requires_authentication(self, org_client):
        res = org_client.get(f"/api/orgs/{uuid.uuid4()}/presence")
        assert res.status_code == 401

    def test_get_presence_returns_bulk_status_for_every_member(self):
        from app.routers.organizations import get_presence
        from app.tenancy import OrgContext

        member_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        fake_tenancy = MagicMock()
        fake_tenancy.list_members = AsyncMock(return_value=[
            {"user_id": member_ids[0]}, {"user_id": member_ids[1]},
        ])
        fake_presence = MagicMock()
        fake_presence.bulk_status = AsyncMock(return_value={member_ids[0]: True, member_ids[1]: False})

        ctx = OrgContext(org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
                          user_email="admin@example.com", role="admin")

        with patch("app.routers.organizations.get_tenancy_service", return_value=fake_tenancy), \
             patch("app.core.presence.get_presence_service", return_value=fake_presence):
            result = run(get_presence(ctx=ctx))

        assert result == {"presence": {member_ids[0]: True, member_ids[1]: False}}
        fake_presence.bulk_status.assert_awaited_once_with(member_ids)


# ── WS: presence heartbeat over the notifications socket ───────────────────────

@pytest.fixture()
def ws_client():
    from fastapi import FastAPI
    from app.routers.ws import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestPresenceOverNotificationsSocket:
    def test_connect_touches_presence_and_ping_frame_refreshes_it(self, ws_client):
        fake_presence = MagicMock()
        fake_presence.touch = AsyncMock(return_value=True)
        fake_presence.mark_offline = AsyncMock()

        with patch("app.core.presence.get_presence_service", return_value=fake_presence):
            with ws_client.websocket_connect(f"/ws/notifications?token={_token()}") as ws:
                connected = ws.receive_json()
                assert connected["type"] == "connected"
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"

        # Once on connect, once for the explicit client ping.
        assert fake_presence.touch.await_count == 2
        fake_presence.mark_offline.assert_awaited_once()

    def test_unauthenticated_connection_never_touches_presence(self, ws_client):
        fake_presence = MagicMock()
        fake_presence.touch = AsyncMock()

        with patch("app.core.presence.get_presence_service", return_value=fake_presence):
            with pytest.raises(Exception):  # noqa: B017 - starlette raises WebSocketDisconnect on close(4401)
                with ws_client.websocket_connect("/ws/notifications") as ws:
                    ws.receive_json()

        fake_presence.touch.assert_not_awaited()
