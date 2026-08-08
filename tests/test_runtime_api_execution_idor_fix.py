"""
Regression tests for the CRITICAL runtime execution IDOR fix (see
app/routers/runtime_api.py's module docstring and
_require_owned_execution()).

GET /api/runtime/{id}/status|report|artifacts|artifacts/{aid} and
DELETE /api/runtime/{id} previously relied solely on api_auth_middleware's
"/api/ requires *some* valid token" gate — the in-memory `_executions`
registry carried no ownership information at all, so any authenticated
user who learned or guessed an execution_id could read another user's
execution status/report/artifacts, or cancel their still-running
execution outright.

Confirmed against this session's git-worktree audit (commit 80197167 on a
stale, never-merged branch fixed the same class of bug via org_context
instead of per-user ownership); this file verifies the per-user ownership
guard actually implemented against current main's code (execute() itself
already established per-user, not per-org, ownership — see
tests/test_runtime_execute_workspace_trust_fix.py).
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


class TestRuntimeExecutionRoutesRequireOwnership(unittest.TestCase):
    def _app(self):
        from fastapi import FastAPI
        from app.routers.runtime_api import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, requester_uid):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=requester_uid)  # owner_user_id() only
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def _seed_execution(self, execution_id: str, owner_uid: str):
        from app.routers.runtime_api import _executions
        _executions[execution_id] = {
            "status": "done", "report": {"secret": "alice's data"},
            "workspace": "/some/path", "owner_uid": owner_uid,
        }
        self.addCleanup(_executions.pop, execution_id, None)

    def test_non_owner_status_is_404(self):
        alice_uid = str(uuid.uuid4())
        bob_uid = uuid.uuid4()
        execution_id = str(uuid.uuid4())
        self._seed_execution(execution_id, alice_uid)

        pool = self._mock_pool(requester_uid=bob_uid)
        with patch("app.routers.runtime_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                res = c.get(f"/api/runtime/{execution_id}/status",
                            headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(res.status_code, 404)

    def test_non_owner_report_does_not_leak_data(self):
        alice_uid = str(uuid.uuid4())
        bob_uid = uuid.uuid4()
        execution_id = str(uuid.uuid4())
        self._seed_execution(execution_id, alice_uid)

        pool = self._mock_pool(requester_uid=bob_uid)
        with patch("app.routers.runtime_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                res = c.get(f"/api/runtime/{execution_id}/report",
                            headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(res.status_code, 404)
        self.assertNotIn("secret", res.text)

    def test_non_owner_cannot_cancel(self):
        """The sabotage/DoS vector: cancel must not succeed, and the
        record must not be removed, for a non-owner."""
        alice_uid = str(uuid.uuid4())
        bob_uid = uuid.uuid4()
        execution_id = str(uuid.uuid4())
        self._seed_execution(execution_id, alice_uid)

        pool = self._mock_pool(requester_uid=bob_uid)
        with patch("app.routers.runtime_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"):
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                res = c.delete(f"/api/runtime/{execution_id}",
                               headers={"X-Sub-Token": "bob-token"})
        self.assertEqual(res.status_code, 404)

        from app.routers.runtime_api import _executions
        self.assertIn(execution_id, _executions)

    def test_owner_can_still_read_status_and_cancel(self):
        alice_uid = uuid.uuid4()
        execution_id = str(uuid.uuid4())
        self._seed_execution(execution_id, str(alice_uid))

        pool = self._mock_pool(requester_uid=alice_uid)
        with patch("app.routers.runtime_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="alice@example.com"):
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                status_res = c.get(f"/api/runtime/{execution_id}/status",
                                    headers={"X-Sub-Token": "alice-token"})
                cancel_res = c.delete(f"/api/runtime/{execution_id}",
                                       headers={"X-Sub-Token": "alice-token"})

        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(cancel_res.status_code, 200)

    def test_unauthenticated_request_rejected_by_full_app(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport
        from app.factory import create_app

        execution_id = str(uuid.uuid4())
        self._seed_execution(execution_id, str(uuid.uuid4()))

        async def _run():
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(f"/api/runtime/{execution_id}/status")

        res = asyncio.run(_run())
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
