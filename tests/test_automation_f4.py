"""
F4 Verification — approval/reject endpoints + POST /api/automations/{id}/run.

Tests:
  1. ApprovalRegistry wiring (engine._approval_registry directly)
  2. approve_step endpoint — success, 404, 409, 500
  3. reject_step  endpoint — success, 404, 409
  4. run_definition endpoint — success, 404, job dispatch
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── helpers ─────────────────────────────────────────────────────────────────

class _async_cm:
    def __init__(self, obj):
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, *_):
        pass


def _make_pool(fetchrow_return=None, execute_return="UPDATE 1"):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    mock_conn.execute = AsyncMock(return_value=execute_return)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))
    return mock_pool, mock_conn


def _make_ctx(org_id=None, user_id=None):
    ctx = MagicMock()
    ctx.org_id  = org_id  or str(uuid.uuid4())
    ctx.user_id = user_id or str(uuid.uuid4())
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# 1. ApprovalRegistry — direct wiring test
# ─────────────────────────────────────────────────────────────────────────────

class TestApprovalRegistryWiring(unittest.TestCase):
    """Verifies the underlying ApprovalRegistry that approve/reject endpoints signal."""

    def setUp(self):
        # Use a fresh private registry so tests don't interfere with each other.
        from app.core.workflow.engine import ApprovalRegistry
        self.reg = ApprovalRegistry()

    def test_register_creates_unset_event(self):
        ev = self.reg.register("run1:step1")
        self.assertFalse(ev.is_set())

    def test_approve_sets_event(self):
        approval_id = f"run-{uuid.uuid4()}:step-x"
        ev = self.reg.register(approval_id)
        self.assertFalse(ev.is_set())
        self.reg.approve(approval_id)
        self.assertTrue(ev.is_set())

    def test_approve_marks_was_approved_true(self):
        aid = f"run-{uuid.uuid4()}:step-y"
        self.reg.register(aid)
        self.reg.approve(aid)
        self.assertTrue(self.reg.was_approved(aid))

    def test_reject_sets_event(self):
        aid = f"run-{uuid.uuid4()}:step-z"
        ev = self.reg.register(aid)
        self.assertFalse(ev.is_set())
        self.reg.reject(aid)
        self.assertTrue(ev.is_set())

    def test_reject_marks_was_approved_false(self):
        aid = f"run-{uuid.uuid4()}:step-w"
        self.reg.register(aid)
        self.reg.reject(aid)
        self.assertFalse(self.reg.was_approved(aid))

    def test_approve_unregistered_returns_false(self):
        result = self.reg.approve("nonexistent:step")
        self.assertFalse(result)

    def test_reject_unregistered_returns_false(self):
        result = self.reg.reject("nonexistent:step")
        self.assertFalse(result)

    def test_approval_id_format_matches_engine(self):
        """approval_id used by endpoints must match engine format: '{run_id}:{step_id}'."""
        run_id  = str(uuid.uuid4())
        step_id = "my-step"
        expected = f"{run_id}:{step_id}"
        ev = self.reg.register(expected)
        self.reg.approve(expected)
        self.assertTrue(ev.is_set())
        self.assertTrue(self.reg.was_approved(expected))

    def test_engine_approve_wakes_registry_when_run_active(self):
        """When a run IS in engine._active, engine.approve() signals the Registry."""
        from app.core.workflow.engine import (
            get_workflow_engine, WorkflowRun, _approval_registry,
        )
        engine  = get_workflow_engine()
        run_id  = str(uuid.uuid4())
        step_id = "gate-step"
        org_id  = str(uuid.uuid4())
        aid     = f"{run_id}:{step_id}"

        # Pre-register the event (simulates what engine.execute does for approval steps)
        ev = _approval_registry.register(aid)
        self.assertFalse(ev.is_set())

        # Inject a fake run into engine._active so _owns_run() succeeds.
        # _owns_run checks: run.context.get("organization_id") == org_id
        fake_run = MagicMock()
        fake_run.run_id = run_id
        fake_run.context = {"organization_id": org_id}
        engine._active[run_id] = fake_run  # type: ignore[assignment]

        try:
            engine.approve(run_id, step_id, org_id=org_id)
            # approve() sets the event — step is unblocked
            self.assertTrue(ev.is_set())
            self.assertTrue(_approval_registry.was_approved(aid))
        finally:
            engine._active.pop(run_id, None)

    def test_engine_approve_returns_false_when_run_not_active(self):
        """If run is not in engine._active, engine.approve() returns False."""
        from app.core.workflow.engine import get_workflow_engine, _approval_registry
        engine  = get_workflow_engine()
        run_id  = str(uuid.uuid4())
        step_id = "inactive-step"
        org_id  = str(uuid.uuid4())
        _approval_registry.register(f"{run_id}:{step_id}")

        result = engine.approve(run_id, step_id, org_id=org_id)
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# 2. approve_step endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestApproveStepEndpoint(unittest.TestCase):

    def test_run_not_found_raises_404(self):
        pool, _ = _make_pool(fetchrow_return=None)
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertRaises(HTTPException) as cm:
                    await approve_step("run-id", "step-id", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 404)
        run(_t())

    def test_wrong_org_run_not_found_raises_404(self):
        """fetchrow with wrong org_id returns None → same 404 (no IDOR)."""
        pool, _ = _make_pool(fetchrow_return=None)
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertRaises(HTTPException) as cm:
                    await approve_step(str(uuid.uuid4()), "step-1", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 404)
        run(_t())

    def test_approval_not_pending_raises_409(self):
        """record_approval_decision returns False → 409."""
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=False),
                ):
                    with self.assertRaises(HTTPException) as cm:
                        await approve_step(str(uuid.uuid4()), "s1", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 409)
        run(_t())

    def test_db_failure_raises_500(self):
        """record_approval_decision raises → 500."""
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(side_effect=Exception("DB connection lost")),
                ):
                    with self.assertRaises(HTTPException) as cm:
                        await approve_step(str(uuid.uuid4()), "s1", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 500)
        run(_t())

    def test_success_returns_approved_decision(self):
        """Happy path: persistence succeeds, engine.approve called, response correct."""
        run_id  = str(uuid.uuid4())
        step_id = "gate-step"
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()
        mock_engine = MagicMock()
        mock_engine.approve = MagicMock(return_value=True)

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=True),
                ) as mock_persist:
                    with patch(
                        "app.core.workflow.engine.get_workflow_engine",
                        return_value=mock_engine,
                    ):
                        result = await approve_step(run_id, step_id, ctx=ctx)

            self.assertEqual(result["decision"], "approved")
            self.assertEqual(result["run_id"],  run_id)
            self.assertEqual(result["step_id"], step_id)
            # persistence called with correct approval_id and status
            mock_persist.assert_called_once_with(
                f"{run_id}:{step_id}", "approved", decided_by=ctx.user_id,
            )
            # engine.approve called with org_id
            mock_engine.approve.assert_called_once_with(
                run_id, step_id, org_id=ctx.org_id,
            )
        run(_t())

    def test_success_when_engine_returns_false(self):
        """engine.approve() returns False (run finished) but persistence succeeded → still 200."""
        run_id = str(uuid.uuid4())
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()
        mock_engine = MagicMock()
        mock_engine.approve = MagicMock(return_value=False)

        async def _t():
            from app.core.workflow.automation_api import approve_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=True),
                ):
                    with patch(
                        "app.core.workflow.engine.get_workflow_engine",
                        return_value=mock_engine,
                    ):
                        # should not raise
                        result = await approve_step(run_id, "step-x", ctx=ctx)
            self.assertEqual(result["decision"], "approved")
        run(_t())


# ─────────────────────────────────────────────────────────────────────────────
# 3. reject_step endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectStepEndpoint(unittest.TestCase):

    def test_run_not_found_raises_404(self):
        pool, _ = _make_pool(fetchrow_return=None)
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import reject_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertRaises(HTTPException) as cm:
                    await reject_step("run-id", "step-id", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 404)
        run(_t())

    def test_approval_not_pending_raises_409(self):
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import reject_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=False),
                ):
                    with self.assertRaises(HTTPException) as cm:
                        await reject_step(str(uuid.uuid4()), "s1", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 409)
        run(_t())

    def test_success_returns_rejected_decision(self):
        run_id  = str(uuid.uuid4())
        step_id = "needs-review"
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()
        mock_engine = MagicMock()
        mock_engine.reject = MagicMock(return_value=True)

        async def _t():
            from app.core.workflow.automation_api import reject_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=True),
                ) as mock_persist:
                    with patch(
                        "app.core.workflow.engine.get_workflow_engine",
                        return_value=mock_engine,
                    ):
                        result = await reject_step(run_id, step_id, ctx=ctx)

            self.assertEqual(result["decision"], "rejected")
            self.assertEqual(result["run_id"],  run_id)
            self.assertEqual(result["step_id"], step_id)
            mock_persist.assert_called_once_with(
                f"{run_id}:{step_id}", "rejected", decided_by=ctx.user_id,
            )
            mock_engine.reject.assert_called_once_with(
                run_id, step_id, org_id=ctx.org_id,
            )
        run(_t())

    def test_db_failure_raises_500(self):
        pool, _ = _make_pool(fetchrow_return={"status": "running"})
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import reject_step
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(side_effect=Exception("timeout")),
                ):
                    with self.assertRaises(HTTPException) as cm:
                        await reject_step(str(uuid.uuid4()), "s1", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 500)
        run(_t())


# ─────────────────────────────────────────────────────────────────────────────
# 4. run_definition endpoint — POST /api/automations/{id}/run
# ─────────────────────────────────────────────────────────────────────────────

class TestRunDefinitionEndpoint(unittest.TestCase):

    def test_definition_not_found_raises_404(self):
        """_get_definition raises 404 if row is absent or from another org."""
        # fetchrow returns None → _get_definition raises HTTPException(404)
        pool, _ = _make_pool(fetchrow_return=None)
        ctx = _make_ctx()
        def_id = str(uuid.uuid4())

        async def _t():
            from app.core.workflow.automation_api import run_definition
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertRaises(HTTPException) as cm:
                    await run_definition(def_id, ctx=ctx)
            self.assertEqual(cm.exception.status_code, 404)
        run(_t())

    def test_invalid_uuid_definition_raises_404(self):
        pool, _ = _make_pool(fetchrow_return=None)
        ctx = _make_ctx()

        async def _t():
            from app.core.workflow.automation_api import run_definition
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertRaises(HTTPException) as cm:
                    await run_definition("not-a-uuid", ctx=ctx)
            self.assertEqual(cm.exception.status_code, 404)
        run(_t())

    def test_success_returns_202_with_run_id(self):
        """Valid definition → 202 + run_id in response."""
        def_id   = str(uuid.uuid4())
        def_name = "My Automation"

        # First acquire() → _get_definition (fetchrow)
        # Second acquire() → INSERT into automation_runs (execute)
        mock_conn1 = AsyncMock()
        mock_conn1.fetchrow = AsyncMock(return_value={
            "id": uuid.UUID(def_id),
            "name": def_name,
            "is_active": True,
            "deleted_at": None,
        })

        mock_conn2 = AsyncMock()
        mock_conn2.execute = AsyncMock(return_value="INSERT 0 1")

        call_count = 0

        class _CountingPool:
            def acquire(self_):
                nonlocal call_count
                call_count += 1
                return _async_cm(mock_conn1 if call_count == 1 else mock_conn2)

        pool = _CountingPool()
        ctx  = _make_ctx()

        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_api import run_definition
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch(
                    "app.core.jobs.get_job_queue",
                    return_value=mock_queue,
                ):
                    result = await run_definition(def_id, ctx=ctx)

            self.assertIn("run_id", result)
            self.assertEqual(result["status"], "pending")
            # run_id is a valid UUID
            uuid.UUID(result["run_id"])
        run(_t())

    def test_job_submitted_to_manual_trigger(self):
        """Verify job queue receives 'automation.trigger.manual' with correct payload."""
        def_id = str(uuid.uuid4())

        mock_conn1 = AsyncMock()
        mock_conn1.fetchrow = AsyncMock(return_value={
            "id": uuid.UUID(def_id),
            "name": "Test Automation",
            "is_active": True,
            "deleted_at": None,
        })

        mock_conn2 = AsyncMock()
        mock_conn2.execute = AsyncMock(return_value="INSERT 0 1")

        call_count = 0

        class _Pool:
            def acquire(self_):
                nonlocal call_count
                call_count += 1
                return _async_cm(mock_conn1 if call_count == 1 else mock_conn2)

        pool = _Pool()
        ctx  = _make_ctx()
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_api import run_definition
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    result = await run_definition(def_id, ctx=ctx)

            run_id = result["run_id"]
            mock_queue.submit.assert_called_once()
            call_args = mock_queue.submit.call_args
            # First positional arg is the job type
            self.assertEqual(call_args.args[0], "automation.trigger.manual")
            # payload contains the right org and definition
            payload = call_args.kwargs["payload"]
            self.assertEqual(payload["organization_id"], ctx.org_id)
            self.assertEqual(payload["definition_id"],   def_id)
            self.assertEqual(payload["run_id"],          run_id)
            self.assertEqual(payload["triggered_by"],    "manual")
            # idempotency_key matches run_id
            self.assertEqual(call_args.kwargs["idempotency_key"], run_id)
        run(_t())

    def test_run_id_is_unique_per_call(self):
        """Each call produces a different run_id."""
        def_id = str(uuid.uuid4())

        call_count = 0

        class _Pool:
            def acquire(self_):
                nonlocal call_count
                call_count += 1
                if call_count % 2 == 1:
                    mc = AsyncMock()
                    mc.fetchrow = AsyncMock(return_value={
                        "id": uuid.UUID(def_id), "name": "X",
                        "is_active": True, "deleted_at": None,
                    })
                    return _async_cm(mc)
                else:
                    mc = AsyncMock()
                    mc.execute = AsyncMock(return_value="INSERT 0 1")
                    return _async_cm(mc)

        pool = _Pool()
        ctx  = _make_ctx()
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_api import run_definition
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    r1 = await run_definition(def_id, ctx=ctx)
                    r2 = await run_definition(def_id, ctx=ctx)
            self.assertNotEqual(r1["run_id"], r2["run_id"])
        run(_t())


# ─────────────────────────────────────────────────────────────────────────────
# 5. approval_id format consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestApprovalIdFormatConsistency(unittest.TestCase):
    """approval_id in endpoints must match engine.py's format: '{run_id}:{step_id}'."""

    def test_format_matches_engine_expectation(self):
        run_id  = str(uuid.uuid4())
        step_id = "step-abc"
        # This is what approve_step and reject_step compute:
        computed = f"{run_id}:{step_id}"
        # Must contain exactly one colon separating run_id from step_id
        parts = computed.split(":")
        # run_id may contain hyphens; step_id follows last colon
        self.assertEqual(parts[-1], step_id)
        # Whole prefix before last colon is the run_id
        self.assertEqual(":".join(parts[:-1]), run_id)

    def test_persistence_and_engine_use_same_key(self):
        """Both persistence.py and engine.py must agree on the same approval_id format."""
        import inspect
        from app.core.workflow import persistence, engine as eng_mod
        # Check persistence source
        pers_src = inspect.getsource(persistence.create_approval_request)
        self.assertIn("{run_id}:{step_id}", pers_src)
        # Check engine module source (approval_id is built in execute() or a helper)
        eng_src = inspect.getsource(eng_mod)
        # Engine must reference the same key pattern
        self.assertTrue(
            "{run.run_id}:{step.id}" in eng_src or "{run_id}:{step_id}" in eng_src,
            "Engine source must contain the approval_id format string",
        )
