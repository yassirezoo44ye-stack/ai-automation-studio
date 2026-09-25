"""
Tests for workflow.approval.pending / workflow.approval.decided event emission
(Phase 1B). Verifies:
  - approval.pending published when a step enters WAITING
  - approval.decided published with decision="approved" after approve_step
  - approval.decided published with decision="rejected" after reject_step
  - notification failure never breaks workflow execution
  - new event types are declared in EVENT_TYPES
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.events.bus import EVENT_TYPES
from app.core.workflow.engine import (
    WorkflowBuilder, WorkflowStatus, StepStatus,
    get_workflow_engine, get_approval_registry,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # drain any pending create_task callbacks before closing
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


async def _noop(_context, _run_id, **_):
    return {}


# ── Event type declaration ──────────────────────────────────────────────────────

class TestEventTypesDeclaration(unittest.TestCase):
    def test_approval_pending_declared(self):
        self.assertIn("workflow.approval.pending", EVENT_TYPES)

    def test_approval_decided_declared(self):
        self.assertIn("workflow.approval.decided", EVENT_TYPES)


# ── Approval pending notification ─────────────────────────────────────────────

class TestApprovalPendingEvent(unittest.TestCase):
    def test_pending_published_when_step_waits(self):
        """approval.pending must be published when engine enters WAITING."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        async def go():
            wf = (WorkflowBuilder("notif-pending")
                  .step("gate", "Gate", _noop, requires_approval=True, timeout_s=2.0)
                  .build(context={"organization_id": "org-test"}))
            approval_id = f"{wf.run_id}:gate"

            async def approve_shortly():
                await asyncio.sleep(0.05)
                get_approval_registry().approve(approval_id)

            asyncio.create_task(approve_shortly())
            return await get_workflow_engine().execute(wf)

        with patch("app.core.events.bus._bus", mock_bus):
            result = run(go())

        self.assertEqual(result.status, WorkflowStatus.COMPLETED)

        pending_calls = [
            c for c in mock_bus.publish.call_args_list
            if c.args and c.args[0] == "workflow.approval.pending"
        ]
        self.assertTrue(pending_calls, "workflow.approval.pending was never published")
        data = pending_calls[0].args[1]
        self.assertIn("run_id", data)
        self.assertEqual(data["step_id"], "gate")

    def test_pending_carries_org_id(self):
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        async def go():
            wf = (WorkflowBuilder("notif-org")
                  .step("gate", "Gate", _noop, requires_approval=True, timeout_s=2.0)
                  .build(context={"organization_id": "org-123"}))
            approval_id = f"{wf.run_id}:gate"

            async def approve_shortly():
                await asyncio.sleep(0.05)
                get_approval_registry().approve(approval_id)

            asyncio.create_task(approve_shortly())
            return await get_workflow_engine().execute(wf)

        with patch("app.core.events.bus._bus", mock_bus):
            run(go())

        pending_calls = [
            c for c in mock_bus.publish.call_args_list
            if c.args and c.args[0] == "workflow.approval.pending"
        ]
        self.assertTrue(pending_calls)
        kwargs = pending_calls[0].kwargs
        self.assertEqual(kwargs.get("organization_id"), "org-123")


# ── Approval decided notification ─────────────────────────────────────────────

class TestApprovalDecidedEvent(unittest.TestCase):
    """
    Runs a real workflow with an approval gate, then calls the API endpoint
    (approve_step / reject_step) with the actual run_id so engine._owns_run
    passes and the decided notification is emitted.
    """

    def _run_full_approval_cycle(self, decision: str) -> list:
        """
        Return mock_bus.publish.call_args_list after running a workflow
        that is approved/rejected via the API endpoint.
        """
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        async def go():
            wf = (WorkflowBuilder(f"api-{decision}")
                  .step("gate", "Gate", _noop, requires_approval=True, timeout_s=5.0)
                  .build(context={"organization_id": "org-api"}))
            run_id = wf.run_id

            async def act_via_endpoint():
                await asyncio.sleep(0.1)
                ctx = MagicMock()
                ctx.org_id = "org-api"
                ctx.user_id = "tester"
                with patch(
                    "app.core.workflow.persistence.record_approval_decision",
                    new=AsyncMock(return_value=True),
                ):
                    if decision == "approved":
                        from app.routers.workflow_api import approve_step
                        await approve_step(run_id, "gate", ctx)
                    else:
                        from app.routers.workflow_api import reject_step
                        await reject_step(run_id, "gate", ctx)

            asyncio.create_task(act_via_endpoint())
            return await get_workflow_engine().execute(wf)

        with patch("app.core.events.bus._bus", mock_bus):
            run(go())

        return mock_bus.publish.call_args_list

    def test_approved_emits_decided_approved(self):
        calls = self._run_full_approval_cycle("approved")
        decided = [c for c in calls if c.args and c.args[0] == "workflow.approval.decided"]
        self.assertTrue(decided, "workflow.approval.decided was never published after approve")
        self.assertEqual(decided[0].args[1]["decision"], "approved")
        self.assertEqual(decided[0].args[1]["step_id"], "gate")

    def test_rejected_emits_decided_rejected(self):
        calls = self._run_full_approval_cycle("rejected")
        decided = [c for c in calls if c.args and c.args[0] == "workflow.approval.decided"]
        self.assertTrue(decided, "workflow.approval.decided was never published after reject")
        self.assertEqual(decided[0].args[1]["decision"], "rejected")
        self.assertEqual(decided[0].args[1]["step_id"], "gate")


# ── Notification failure isolation ────────────────────────────────────────────

class TestNotificationFailureIsolation(unittest.TestCase):
    def test_bus_publish_failure_does_not_break_workflow(self):
        """Notification crash must not propagate to workflow execution."""
        failing_bus = AsyncMock()
        failing_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))

        async def go():
            wf = (WorkflowBuilder("notif-fail")
                  .step("gate", "Gate", _noop, requires_approval=True, timeout_s=2.0)
                  .build())
            approval_id = f"{wf.run_id}:gate"

            async def approve_shortly():
                await asyncio.sleep(0.05)
                get_approval_registry().approve(approval_id)

            asyncio.create_task(approve_shortly())
            return await get_workflow_engine().execute(wf)

        with patch("app.core.events.bus._bus", failing_bus):
            result = run(go())

        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.steps["gate"].status, StepStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
