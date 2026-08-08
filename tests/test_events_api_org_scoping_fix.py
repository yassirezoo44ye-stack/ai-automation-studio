"""
Regression tests for the CRITICAL /api/events/replay + /api/events/dlq
cross-tenant leak fix (see app/routers/events_api.py's docstring and
app/core/events/bus.py's EventBus.replay()/dead_letters()).

Every Event carries its own organization_id, but the bus previously
returned every org's history/dead-letters to any authenticated caller
with zero filtering. Confirmed against this session's git-worktree audit
(commit 6bc86b87 on a stale, never-merged branch fixed this identically);
this file re-implements and re-verifies the fix against current main's
actual code.
"""
from __future__ import annotations

import asyncio
import time
import unittest

from app.core.events.bus import Event, EventBus


class TestEventBusReplayIsOrgScoped(unittest.TestCase):
    def _bus_with_events(self) -> EventBus:
        bus = EventBus()
        bus._history = [
            Event(type="job.completed", data={}, ts=time.time(), organization_id="org-a"),
            Event(type="job.completed", data={}, ts=time.time(), organization_id="org-b"),
            Event(type="job.completed", data={}, ts=time.time(), organization_id=None),
        ]
        return bus

    def test_unscoped_default_returns_every_org(self):
        """Internal/system callers that don't pass org_id keep the old,
        unscoped behavior — this must not silently start filtering
        internal call sites that never had a tenant boundary."""
        bus = self._bus_with_events()
        events = asyncio.run(bus.replay())
        self.assertEqual(len(events), 3)

    def test_scoped_to_one_org_excludes_others(self):
        bus = self._bus_with_events()
        events = asyncio.run(bus.replay(org_id="org-a"))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].organization_id, "org-a")

    def test_scoped_to_no_org_excludes_every_tenant(self):
        """org_id=None must mean 'the no-org bucket', not 'everything' —
        the exact distinction _UNSCOPED exists to make explicit."""
        bus = self._bus_with_events()
        events = asyncio.run(bus.replay(org_id=None))
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].organization_id)


class TestEventBusDeadLettersIsOrgScoped(unittest.TestCase):
    def _bus_with_dlq(self) -> EventBus:
        bus = EventBus()
        bus._dlq = [
            {"event": {"organization_id": "org-a"}, "handler": "h", "error": "e", "ts": 1.0},
            {"event": {"organization_id": "org-b"}, "handler": "h", "error": "e", "ts": 2.0},
        ]
        return bus

    def test_unscoped_default_returns_every_org(self):
        bus = self._bus_with_dlq()
        self.assertEqual(len(bus.dead_letters()), 2)

    def test_scoped_to_one_org_excludes_others(self):
        bus = self._bus_with_dlq()
        entries = bus.dead_letters(org_id="org-a")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"]["organization_id"], "org-a")


class TestEventsApiRequiresOrgContext(unittest.TestCase):
    """The router layer: /replay and /dlq must require a verified org
    context (same as jobs_api.py), not just "any authenticated user"."""

    def _app(self):
        from fastapi import FastAPI
        from app.routers.events_api import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_replay_without_org_header_is_rejected(self):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient

        app = self._app()
        with patch("app.routers.auth_users.get_current_user",
                   new=AsyncMock(return_value={"id": "u1", "email": "a@b.com"})):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/events/replay")
        self.assertEqual(res.status_code, 400)

    def test_dlq_without_org_header_is_rejected(self):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient

        app = self._app()
        with patch("app.routers.auth_users.get_current_user",
                   new=AsyncMock(return_value={"id": "u1", "email": "a@b.com"})):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/events/dlq")
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
