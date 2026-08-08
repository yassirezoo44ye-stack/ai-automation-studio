"""
Regression tests for the CRITICAL POST /api/runtime/execute fix (see
app/routers/runtime_api.py::execute's docstring).

Previously the endpoint accepted a client-supplied `workspace` absolute
path string and handed it straight to UnifiedExecutionEngine.run(), which
copies that directory into a sandbox and runs install/build/launch against
it. The route required a valid session (api_auth_middleware) but nothing
tied the path to the caller's own project — any authenticated user could
point the engine at another org's workspace or any directory readable by
the server process: an arbitrary-file-read + arbitrary-code-execution
primitive gated by nothing but a valid session.

Fix: `workspace` removed from the request body; the workspace is now
derived server-side from a verified project_id via owner_user_id() +
resolve_project_id() (build.py's ownership pattern) and
app.core.filesystem.workspace() (path-traversal-safe, confined to
WORKSPACES/).

Same mocking pattern as tests/security/test_api_security.py's
TestBuildProjectEndpointsRequireOwnership.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


class TestRuntimeExecuteRequiresOwnership(unittest.TestCase):
    def _app(self):
        from fastapi import FastAPI
        from app.routers.runtime_api import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _mock_pool(self, *, requester_uid, owns_project: bool):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=[
            requester_uid,                  # owner_user_id() resolves the caller
            1 if owns_project else None,    # resolve_project_id()'s ownership SELECT
        ])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool

    def test_unauthenticated_request_rejected_by_full_app(self):
        """No X-Sub-Token/JWT at all: api_auth_middleware must reject
        before the handler (and its ownership check) ever runs.

        Uses AsyncClient + ASGITransport (no lifespan) rather than
        TestClient(create_app()) as a context manager, same as
        test_api_security.py's equivalent test — lifespan startup tries a
        real DB connection this environment doesn't have."""
        import asyncio
        from httpx import AsyncClient, ASGITransport
        from app.factory import create_app

        async def _run():
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/runtime/execute", json={"project_id": "some-id"})

        res = asyncio.run(_run())
        self.assertEqual(res.status_code, 401)

    def test_non_owner_gets_404_not_execution(self):
        """Bob authenticates fine, but the project belongs to Alice —
        the engine must never run against her workspace."""
        bob_uid = uuid.uuid4()
        other_project_id = str(uuid.uuid4())
        app = self._app()
        pool = self._mock_pool(requester_uid=bob_uid, owns_project=False)

        with patch("app.routers.runtime_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="bob@example.com"), \
             patch("app.routers.runtime_api.UnifiedExecutionEngine") as MockEngine:
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/runtime/execute",
                    json={"project_id": other_project_id},
                    headers={"X-Sub-Token": "bob-token"},
                )
        self.assertEqual(res.status_code, 404)
        MockEngine.assert_not_called()

    def test_client_supplied_workspace_field_is_ignored(self):
        """Even if a caller still sends a `workspace` path in the body
        (old client, or an attacker probing for the old field), it must
        have zero effect — the server-derived path is always used."""
        alice_uid = uuid.uuid4()
        project_id = str(uuid.uuid4())
        app = self._app()
        pool = self._mock_pool(requester_uid=alice_uid, owns_project=True)

        captured = {}

        async def _fake_run(ws, project_id="", execution_id=None, options=None):
            captured["workspace"] = ws
            return
            yield  # pragma: no cover - makes this an async generator

        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.routers.runtime_api.get_pool", return_value=pool), \
                 patch("app.core.auth.owner_email", return_value="alice@example.com"), \
                 patch("app.core.filesystem.WORKSPACES", Path(tmp)), \
                 patch("app.routers.runtime_api.UnifiedExecutionEngine") as MockEngine:
                MockEngine.return_value.run = _fake_run
                with TestClient(app, raise_server_exceptions=False) as c:
                    res = c.post(
                        "/api/runtime/execute",
                        json={
                            "project_id": project_id,
                            "workspace": "/etc",  # attacker-supplied, must be ignored
                        },
                        headers={"X-Sub-Token": "alice-token"},
                    )
                    # Drain the SSE stream so the handler body actually runs.
                    list(res.iter_lines())

        self.assertEqual(res.status_code, 200)
        self.assertIn("workspace", captured)
        self.assertTrue(
            str(captured["workspace"]).startswith(str(Path(tmp).resolve())),
            f"engine ran against {captured['workspace']!r}, not the server-derived workspace",
        )
        self.assertNotEqual(str(captured["workspace"]), "/etc")


if __name__ == "__main__":
    unittest.main()
