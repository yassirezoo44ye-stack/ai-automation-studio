"""
Regression tests for the CRITICAL WorkflowEngine cross-tenant approve/
reject/visibility fix (see app/core/workflow/engine.py's
active()/approve()/reject()/pending_approvals() and app/routers/
workflow_api.py's docstring).

WorkflowEngine._active/_approval_registry previously carried no
organization_id at all — active()/pending_approvals() returned every
org's runs, and approve()/reject() never checked which org a run
belonged to before mutating it. Confirmed against this session's
git-worktree audit (commit 56dc8339 on a stale, never-merged branch
fixed this identically, and main's own workflow_api.py docstring
explicitly flagged it as a "KNOWN RESIDUAL GAP (flagged, not fixed
here)"); this file re-implements and re-verifies the fix against
current main's actual code.
"""
from __future__ import annotations

import unittest

from app.core.workflow.engine import WorkflowEngine, WorkflowRun, WorkflowStatus


def _make_run(run_id: str, org_id: str | None) -> WorkflowRun:
    return WorkflowRun(
        run_id=run_id, name="test", steps={},
        status=WorkflowStatus.RUNNING,
        context={"organization_id": org_id} if org_id is not None else {},
    )


class TestWorkflowEngineActiveIsOrgScoped(unittest.TestCase):
    def _engine_with_runs(self) -> WorkflowEngine:
        engine = WorkflowEngine()
        engine._active["run-a"] = _make_run("run-a", "org-a")
        engine._active["run-b"] = _make_run("run-b", "org-b")
        engine._active["run-none"] = _make_run("run-none", None)
        return engine

    def test_unscoped_default_returns_every_org(self):
        engine = self._engine_with_runs()
        self.assertEqual(len(engine.active()), 3)

    def test_scoped_to_one_org_excludes_others(self):
        engine = self._engine_with_runs()
        runs = engine.active(org_id="org-a")
        self.assertEqual([r["run_id"] for r in runs], ["run-a"])

    def test_scoped_to_no_org_excludes_every_tenant(self):
        engine = self._engine_with_runs()
        runs = engine.active(org_id=None)
        self.assertEqual([r["run_id"] for r in runs], ["run-none"])


class TestWorkflowEngineApproveRejectRequireOwnership(unittest.TestCase):
    def _engine_with_runs(self) -> WorkflowEngine:
        engine = WorkflowEngine()
        engine._active["run-a"] = _make_run("run-a", "org-a")
        return engine

    def test_approve_by_owning_org_succeeds(self):
        engine = self._engine_with_runs()
        self.assertTrue(engine.approve("run-a", "step1", org_id="org-a"))

    def test_approve_by_other_org_fails_without_mutation(self):
        """The exact exploit shape: an authenticated user from a
        different org must not be able to approve someone else's
        workflow step."""
        engine = self._engine_with_runs()
        from app.core.workflow.engine import _approval_registry
        self.assertFalse(engine.approve("run-a", "step1", org_id="org-b"))
        self.assertFalse(_approval_registry.was_approved("run-a:step1"))

    def test_reject_by_other_org_fails_without_mutation(self):
        # Distinct step id — _approval_registry is a module-level
        # singleton shared across tests in this process, so reusing
        # "step1" here would collide with test_approve_*'s decision for
        # the same run_id:step_id key.
        engine = self._engine_with_runs()
        from app.core.workflow.engine import _approval_registry
        self.assertFalse(engine.reject("run-a", "step-reject-test", org_id="org-b"))
        self.assertNotIn("run-a:step-reject-test", _approval_registry._decisions)

    def test_approve_nonexistent_run_fails(self):
        engine = self._engine_with_runs()
        self.assertFalse(engine.approve("no-such-run", "step1", org_id="org-a"))

    def test_unscoped_internal_caller_can_still_approve_any_run(self):
        """Internal callers that don't pass org_id keep the old,
        unscoped behavior."""
        engine = self._engine_with_runs()
        self.assertTrue(engine.approve("run-a", "step1"))


class TestWorkflowEnginePendingApprovalsIsOrgScoped(unittest.TestCase):
    def test_pending_approvals_scoped_to_owning_org(self):
        engine = WorkflowEngine()
        engine._active["run-a"] = _make_run("run-a", "org-a")
        engine._active["run-b"] = _make_run("run-b", "org-b")
        from app.core.workflow.engine import _approval_registry
        _approval_registry.register("run-a:step1")
        _approval_registry.register("run-b:step1")

        pending_a = engine.pending_approvals(org_id="org-a")
        self.assertEqual(pending_a, ["run-a:step1"])


class TestWorkflowApiRequiresOrgContext(unittest.TestCase):
    def _app(self):
        from fastapi import FastAPI
        from app.routers.workflow_api import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_active_without_org_header_is_rejected(self):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient

        app = self._app()
        with patch("app.routers.auth_users.get_current_user",
                   new=AsyncMock(return_value={"id": "u1", "email": "a@b.com"})):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.get("/api/workflows/active")
        self.assertEqual(res.status_code, 400)

    def test_approve_without_org_header_is_rejected(self):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient

        app = self._app()
        with patch("app.routers.auth_users.get_current_user",
                   new=AsyncMock(return_value={"id": "u1", "email": "a@b.com"})):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post("/api/workflows/approvals/run-a/step1/approve")
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
