"""
Notification Center tests — service query scoping, router auth/ownership,
event-bus dispatcher mapping, and template/EVENT_TYPES consistency.

No live Postgres — pool/conn are mocked (same pattern as
tests/test_chat_isolation.py and test_observability.py's audit-log tests).
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


# ── NotificationService: query scoping ─────────────────────────────────────────

class TestNotificationServiceScoping:
    def test_list_always_scopes_to_user_id(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = NotificationService(_mock_pool(conn))

        uid = str(uuid.uuid4())
        run(svc.list(user_id=uid, category="billing", search="invoice"))

        sql, *params = conn.fetch.call_args.args
        assert "user_id = $1" in sql
        assert uuid.UUID(uid) in params

    def test_mark_read_scoped_to_owner_returns_false_when_no_row_matched(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")  # WHERE matched nothing
        svc = NotificationService(_mock_pool(conn))

        ok = run(svc.mark_read(user_id=str(uuid.uuid4()), notification_id=str(uuid.uuid4())))

        assert ok is False
        sql = conn.execute.call_args.args[0]
        assert "user_id=$2" in sql or "user_id = $2" in sql

    def test_mark_read_returns_true_when_row_matched(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        svc = NotificationService(_mock_pool(conn))

        ok = run(svc.mark_read(user_id=str(uuid.uuid4()), notification_id=str(uuid.uuid4())))
        assert ok is True

    def test_delete_scoped_to_owner(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 0")
        svc = NotificationService(_mock_pool(conn))

        ok = run(svc.delete(user_id=str(uuid.uuid4()), notification_id=str(uuid.uuid4())))
        assert ok is False
        sql = conn.execute.call_args.args[0]
        assert "user_id=$2" in sql

    def test_mark_all_read_returns_count(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 3")
        svc = NotificationService(_mock_pool(conn))

        count = run(svc.mark_all_read(user_id=str(uuid.uuid4())))
        assert count == 3

    def test_create_rejects_unknown_category(self):
        from app.core.notifications.service import NotificationService
        svc = NotificationService(_mock_pool(AsyncMock()))
        with pytest.raises(ValueError):
            run(svc.create(
                user_id=str(uuid.uuid4()), type_="x", title="t", message="m",
                category="not-a-real-category",
            ))

    def test_set_preferences_rejects_unknown_category(self):
        from app.core.notifications.service import NotificationService
        svc = NotificationService(_mock_pool(AsyncMock()))
        with pytest.raises(ValueError):
            run(svc.set_preferences(user_id=str(uuid.uuid4()), muted_categories=["not-real"]))

    def test_unread_count_scoped_to_user(self):
        from app.core.notifications.service import NotificationService
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=4)
        svc = NotificationService(_mock_pool(conn))

        n = run(svc.unread_count(user_id=str(uuid.uuid4())))
        assert n == 4
        sql, *params = conn.fetchval.call_args.args
        assert "user_id=$1" in sql


# ── Router: auth required, ownership enforced via the service layer ────────────

@pytest.fixture()
def notif_client():
    from fastapi import FastAPI
    from app.routers.notifications import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token():
    from app.core.jwt_utils import make_access_token
    return make_access_token(str(uuid.uuid4()), "user@example.com")


class TestNotificationsRouter:
    def test_list_requires_authentication(self, notif_client):
        res = notif_client.get("/api/notifications")
        assert res.status_code == 401

    def test_list_returns_items_for_authenticated_user(self, notif_client):
        fake_svc = MagicMock()
        fake_svc.list = AsyncMock(return_value=[{"id": "n1", "title": "Hi"}])
        with patch("app.routers.notifications.get_notification_service", return_value=fake_svc):
            res = notif_client.get(
                "/api/notifications", headers={"Authorization": f"Bearer {_token()}"},
            )
        assert res.status_code == 200
        assert res.json()["notifications"] == [{"id": "n1", "title": "Hi"}]

    def test_unknown_category_filter_rejected(self, notif_client):
        res = notif_client.get(
            "/api/notifications?category=not-a-category",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        assert res.status_code == 400

    def test_mark_read_on_foreign_notification_returns_404(self, notif_client):
        """Ownership lives in the service (WHERE user_id=$2) — when it
        reports no row matched, the router must surface 404, not 200."""
        fake_svc = MagicMock()
        fake_svc.mark_read = AsyncMock(return_value=False)
        with patch("app.routers.notifications.get_notification_service", return_value=fake_svc):
            res = notif_client.post(
                f"/api/notifications/{uuid.uuid4()}/read",
                headers={"Authorization": f"Bearer {_token()}"},
            )
        assert res.status_code == 404

    def test_delete_on_own_notification_succeeds(self, notif_client):
        fake_svc = MagicMock()
        fake_svc.delete = AsyncMock(return_value=True)
        with patch("app.routers.notifications.get_notification_service", return_value=fake_svc):
            res = notif_client.delete(
                f"/api/notifications/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {_token()}"},
            )
        assert res.status_code == 204

    def test_set_preferences_rejects_unknown_category(self, notif_client):
        res = notif_client.put(
            "/api/notifications/preferences",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"muted_categories": ["bogus"]},
        )
        assert res.status_code == 400


# ── Dispatcher: event -> notification mapping ───────────────────────────────────

class TestNotificationDispatcher:
    def test_org_scoped_event_fans_out_to_every_member(self):
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        fake_svc.org_member_ids = AsyncMock(return_value=["u1", "u2"])
        fake_svc.is_muted = AsyncMock(return_value=False)
        fake_svc.create = AsyncMock(side_effect=lambda **kw: {**kw, "id": "n1"})

        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        event = Event(type="workflow.completed", data={"run_id": "abc123", "name": "Nightly"},
                      organization_id="org-1")

        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc), \
             patch("app.routers.ws.manager", fake_ws):
            run(handle_event(event))

        assert fake_svc.create.call_count == 2
        assert fake_ws.broadcast.call_count == 2
        first_call = fake_svc.create.call_args_list[0].kwargs
        assert first_call["category"] == "workflow"
        assert first_call["severity"] == "success"
        assert "Nightly" in first_call["title"]

    def test_muted_category_is_skipped(self):
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        fake_svc.org_member_ids = AsyncMock(return_value=["u1"])
        fake_svc.is_muted = AsyncMock(return_value=True)
        fake_svc.create = AsyncMock()

        event = Event(type="workflow.failed", data={"run_id": "x", "error": "boom"},
                      organization_id="org-1")

        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc):
            run(handle_event(event))

        fake_svc.create.assert_not_called()

    def test_event_without_organization_id_is_skipped(self):
        """Can't safely guess who should see it — best-effort no-op."""
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        fake_svc.org_member_ids = AsyncMock()

        event = Event(type="workflow.completed", data={}, organization_id=None)
        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc):
            run(handle_event(event))

        fake_svc.org_member_ids.assert_not_called()

    def test_unmapped_event_type_is_ignored(self):
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        event = Event(type="memory.created", data={}, organization_id="org-1")
        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc):
            run(handle_event(event))  # must not raise despite no template entry

    def test_agent_finished_severity_reflects_success_flag(self):
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        fake_svc.org_member_ids = AsyncMock(return_value=["u1"])
        fake_svc.is_muted = AsyncMock(return_value=False)
        fake_svc.create = AsyncMock(side_effect=lambda **kw: kw)
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        event = Event(type="agent.finished", data={"agent": "Router", "success": False},
                      organization_id="org-1")
        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc), \
             patch("app.routers.ws.manager", fake_ws):
            run(handle_event(event))

        assert fake_svc.create.call_args.kwargs["severity"] == "error"

    def test_dispatch_failure_is_swallowed(self):
        """A broken template/service call must never propagate — the event
        bus's own publisher (workflow engine, billing webhook, ...) must
        keep working even if notifications break."""
        from app.core.notifications.dispatcher import handle_event
        from app.core.events.bus import Event

        fake_svc = MagicMock()
        fake_svc.org_member_ids = AsyncMock(side_effect=RuntimeError("db down"))

        event = Event(type="workflow.completed", data={}, organization_id="org-1")
        with patch("app.core.notifications.service.get_notification_service", return_value=fake_svc):
            run(handle_event(event))  # must not raise


# ── Templates ↔ EVENT_TYPES consistency ─────────────────────────────────────────

class TestNotificationTemplates:
    def test_every_template_key_is_a_declared_event_type(self):
        from app.core.notifications.templates import TEMPLATES
        from app.core.events.bus import EVENT_TYPES
        undeclared = set(TEMPLATES) - EVENT_TYPES
        assert not undeclared, f"templates reference undeclared event types: {undeclared}"

    def test_every_template_category_and_severity_are_valid(self):
        from app.core.notifications.templates import TEMPLATES
        from app.core.notifications.service import CATEGORIES, SEVERITIES
        for event_type, tmpl in TEMPLATES.items():
            assert tmpl.category in CATEGORIES, event_type
            resolved = tmpl.resolve_severity({"success": True})
            assert resolved in SEVERITIES, event_type

    def test_billing_sub_events_are_declared(self):
        """Regression: these two used to be published but never declared in
        EVENT_TYPES, so EventBus.publish() silently threw and the caller's
        try/except swallowed it — the event never actually reached the bus."""
        from app.core.events.bus import EVENT_TYPES
        assert "billing.payment_failed" in EVENT_TYPES
        assert "billing.invoice_paid" in EVENT_TYPES
