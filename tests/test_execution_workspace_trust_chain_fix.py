"""
Regression tests for the CRITICAL workspace-trust + identity-spoofing fix
across the "run" command/agent's remaining entry points beyond
runtime_api.py (see app/routers/commands_api.py, app/routers/
planning_api.py, app/commands/builtin/run_cmd.py,
app/agents/builtin/run_agent.py docstrings).

Previously: POST /api/commands/execute (command "run") and
POST /api/plan/execute both let any authenticated user pass an arbitrary
`workspace` path string, with zero ownership verification, feeding
directly into UnifiedExecutionEngine — the same arbitrary-file-read +
code-execution primitive as runtime_api.py's POST /api/runtime/execute
bug (see tests/test_runtime_execute_workspace_trust_fix.py). commands_api
additionally trusted a client-supplied `user_id` as the acting identity.

Confirmed against this session's git-worktree audit (commit 9d75d424 on a
stale, never-merged branch fixed the router layer identically); this file
re-implements and re-verifies the fix (router + handler layers) against
current main's actual code rather than cherry-picking the stale diff.
"""
from __future__ import annotations

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_pool(*, requester_uid, owns_project: bool):
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[
        requester_uid,                  # owner_user_id() resolves the caller
        1 if owns_project else None,    # resolve_project_id()'s ownership SELECT
    ])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class TestRunCmdRequiresVerifiedProjectOwnership(unittest.TestCase):
    """Handler layer: app/commands/builtin/run_cmd.py must never derive a
    workspace from a client-controlled path again."""

    def test_no_user_id_fails_closed(self):
        from app.commands.builtin.run_cmd import run_handler
        from app.commands.context import CommandContext

        ctx = CommandContext(command="run", flags={"project": "p1"})
        result = asyncio.run(run_handler(ctx))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "UNAUTHENTICATED")

    def test_no_project_id_fails_closed(self):
        from app.commands.builtin.run_cmd import run_handler
        from app.commands.context import CommandContext

        ctx = CommandContext(command="run", user_id=str(uuid.uuid4()))
        result = asyncio.run(run_handler(ctx))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "MISSING_PROJECT")

    def test_non_owner_project_is_rejected_and_engine_never_runs(self):
        from app.commands.builtin.run_cmd import run_handler
        from app.commands.context import CommandContext

        bob_uid = uuid.uuid4()
        ctx = CommandContext(command="run", user_id=str(bob_uid), project_id=str(uuid.uuid4()))
        # run_cmd.py calls resolve_project_id() directly (no owner_user_id
        # lookup — it trusts ctx.user_id, already verified upstream by
        # commands_api.py) — a single fetchval call for the ownership SELECT.
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # not owned
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.db.get_pool", return_value=pool), \
             patch("app.execution.platform.UnifiedExecutionEngine") as MockEngine:
            result = asyncio.run(run_handler(ctx))

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "PROJECT_NOT_FOUND")
        MockEngine.assert_not_called()

    def test_client_supplied_workspace_flag_is_ignored(self):
        """Even the old --workspace flag (now vestigial in CommandContext)
        must have zero effect on the actual path used."""
        from app.commands.builtin.run_cmd import run_handler
        from app.commands.context import CommandContext
        from pathlib import Path
        import tempfile

        alice_uid = uuid.uuid4()
        project_id = str(uuid.uuid4())
        ctx = CommandContext(
            command="run", user_id=str(alice_uid), project_id=project_id,
            workspace=Path("/etc"),  # attacker-supplied, must be ignored
        )
        pool = _mock_pool(requester_uid=alice_uid, owns_project=True)

        captured = {}

        async def _fake_run(ws, project_id=""):
            captured["workspace"] = ws
            return
            yield  # pragma: no cover

        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.core.db.get_pool", return_value=pool), \
                 patch("app.core.filesystem.WORKSPACES", Path(tmp)), \
                 patch("app.execution.platform.UnifiedExecutionEngine") as MockEngine:
                MockEngine.return_value.run = _fake_run
                asyncio.run(run_handler(ctx))

        self.assertIn("workspace", captured)
        self.assertTrue(str(captured["workspace"]).startswith(str(Path(tmp).resolve())))
        self.assertNotEqual(str(captured["workspace"]), "/etc")


class TestCommandsApiNeverTrustsClientUserId(unittest.TestCase):
    """Router layer: POST /api/commands/execute must resolve identity
    from the verified auth token, never the request body."""

    def _app(self):
        from fastapi import FastAPI
        from app.routers.commands_api import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_user_id_field_is_no_longer_accepted_in_the_request_model(self):
        from app.routers.commands_api import ExecuteRequest
        self.assertNotIn("user_id", ExecuteRequest.model_fields)

    def test_execute_uses_verified_identity_not_client_claim(self):
        from fastapi.testclient import TestClient

        real_uid = uuid.uuid4()
        pool = _mock_pool(requester_uid=real_uid, owns_project=True)
        captured = {}

        async def _fake_execute(input_, caller="api", user_id=None):
            captured["user_id"] = user_id
            from app.commands.result import CommandResult
            return CommandResult.ok("noop", output="")

        with patch("app.routers.commands_api.get_pool", return_value=pool), \
             patch("app.core.auth.owner_email", return_value="alice@example.com"), \
             patch("app.routers.commands_api.get_runner") as mock_get_runner:
            mock_get_runner.return_value.execute = _fake_execute
            with TestClient(self._app(), raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/commands/execute",
                    # An old/malicious client trying to smuggle an
                    # impersonated identity via an unknown extra field —
                    # pydantic ignores it, and it must have zero effect.
                    json={"input": "status", "user_id": "someone-elses-id"},
                    headers={"X-Sub-Token": "alice-token"},
                )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(captured["user_id"], str(real_uid))
        self.assertNotEqual(captured["user_id"], "someone-elses-id")


class TestPlanExecuteNeverTrustsClientWorkspaceOrIdentity(unittest.TestCase):
    """Router layer: POST /api/plan/execute must resolve identity from
    the verified auth token and never accept a raw workspace path."""

    def test_workspace_field_is_no_longer_accepted_in_the_request_model(self):
        from app.routers.planning_api import PlanRequest
        self.assertNotIn("workspace", PlanRequest.model_fields)

    def test_execute_requires_authentication(self):
        """Full app (not a bare router) — api_auth_middleware must reject
        an unauthenticated caller before the handler's own get_pool()/
        owner_user_id() call ever runs, same as
        tests/test_runtime_execute_workspace_trust_fix.py's equivalent
        test."""
        import asyncio as _asyncio
        from httpx import AsyncClient, ASGITransport
        from app.factory import create_app

        async def _run():
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/api/plan/execute", json={"goal": "do something"})

        res = _asyncio.run(_run())
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
