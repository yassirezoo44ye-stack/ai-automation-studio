"""
Workflow engine tests — closes a zero-coverage gap on one of the most complex
existing subsystems (DAG execution, parallel branches, conditions, retry,
timeout, human approval, Saga compensation). Pure-logic-testable, no DB
needed — same async-test pattern as tests/test_enterprise.py.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.workflow.engine import (
    WorkflowBuilder, WorkflowStatus, StepStatus, RetryPolicy,
    ApprovalRegistry, get_workflow_engine, _topo_sort,
)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Topological sort ────────────────────────────────────────────────────────────

class TestTopoSort(unittest.TestCase):
    def test_linear_chain(self):
        b = WorkflowBuilder("linear")
        b.step("a", "A", _noop).step("b", "B", _noop, depends_on=["a"])
        b.step("c", "C", _noop, depends_on=["b"])
        groups = _topo_sort(b.build().steps)
        self.assertEqual(groups, [["a"], ["b"], ["c"]])

    def test_diamond_produces_parallel_group(self):
        b = WorkflowBuilder("diamond")
        b.step("a", "A", _noop)
        b.step("b", "B", _noop, depends_on=["a"])
        b.step("c", "C", _noop, depends_on=["a"])
        b.step("d", "D", _noop, depends_on=["b", "c"])
        groups = _topo_sort(b.build().steps)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0], ["a"])
        self.assertEqual(set(groups[1]), {"b", "c"})  # parallel group
        self.assertEqual(groups[2], ["d"])

    def test_independent_steps_form_one_group(self):
        b = WorkflowBuilder("independent")
        b.step("a", "A", _noop).step("b", "B", _noop).step("c", "C", _noop)
        groups = _topo_sort(b.build().steps)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {"a", "b", "c"})

    def test_cycle_raises(self):
        b = WorkflowBuilder("cyclic")
        b.step("a", "A", _noop, depends_on=["b"])
        b.step("b", "B", _noop, depends_on=["a"])
        with self.assertRaises(ValueError):
            _topo_sort(b.build().steps)


# ── WorkflowBuilder ──────────────────────────────────────────────────────────────

class TestWorkflowBuilder(unittest.TestCase):
    def test_fluent_chain_builds_correct_steps(self):
        wf = (WorkflowBuilder("test")
              .step("a", "Step A", _noop)
              .step("b", "Step B", _noop, depends_on=["a"])
              .build(context={"key": "value"}))
        self.assertEqual(wf.name, "test")
        self.assertEqual(set(wf.steps), {"a", "b"})
        self.assertEqual(wf.steps["b"].depends_on, ["a"])
        self.assertEqual(wf.context, {"key": "value"})
        self.assertEqual(wf.status, WorkflowStatus.PENDING)

    def test_each_build_call_gets_a_unique_run_id(self):
        b = WorkflowBuilder("t").step("a", "A", _noop)
        run1, run2 = b.build(), b.build()
        self.assertNotEqual(run1.run_id, run2.run_id)


# ── Step functions used across execution tests ──────────────────────────────────

async def _noop(**kw):
    return {"ok": True}


async def _fail_always(**kw):
    raise RuntimeError("intentional failure")


def _fail_n_times(n: int):
    """Returns a step fn that fails the first n calls, then succeeds."""
    calls = {"count": 0}
    async def _fn(**kw):
        calls["count"] += 1
        if calls["count"] <= n:
            raise RuntimeError(f"attempt {calls['count']} fails")
        return {"succeeded_on_attempt": calls["count"]}
    return _fn


async def _slow(**kw):
    await asyncio.sleep(0.2)
    return {"ok": True}


# ── Linear / parallel execution ──────────────────────────────────────────────────

class TestExecution(unittest.TestCase):
    def test_linear_success_completes_and_merges_context(self):
        async def step_a(**kw):
            return {"value": 1}
        async def step_b(_context, **kw):
            return {"value": _context["a.value"] + 1}

        wf = (WorkflowBuilder("linear")
              .step("a", "A", step_a)
              .step("b", "B", step_b, depends_on=["a"])
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.steps["a"].status, StepStatus.COMPLETED)
        self.assertEqual(result.steps["b"].status, StepStatus.COMPLETED)
        self.assertEqual(result.context["b.value"], 2)

    def test_independent_steps_actually_run_concurrently(self):
        """Two 0.2s steps in the same group should take ~0.2s total, not 0.4s."""
        wf = (WorkflowBuilder("parallel")
              .step("a", "A", _slow)
              .step("b", "B", _slow)
              .build())
        import time
        t0 = time.perf_counter()
        result = run(get_workflow_engine().execute(wf))
        elapsed = time.perf_counter() - t0
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertLess(elapsed, 0.35, "steps in the same group should run in parallel")

    def test_reserved_kwargs_dont_collide_with_step_args(self):
        """step.args containing _context/_run_id keys must not crash the
        framework's own injection of those kwargs (see engine.py comment)."""
        async def step_fn(_context, _run_id, **kw):
            return {"got_context": _context is not None, "got_run_id": _run_id is not None}

        wf = (WorkflowBuilder("reserved")
              .step("a", "A", step_fn, args={"_context": "user-supplied-junk", "_run_id": "also-junk"})
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.steps["a"].result, {"got_context": True, "got_run_id": True})


# ── Conditional branches ─────────────────────────────────────────────────────────

class TestConditions(unittest.TestCase):
    def test_condition_false_skips_step(self):
        wf = (WorkflowBuilder("cond")
              .step("a", "A", _noop, condition=lambda ctx: False)
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.steps["a"].status, StepStatus.SKIPPED)
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)

    def test_condition_true_runs_step(self):
        wf = (WorkflowBuilder("cond")
              .step("a", "A", _noop, condition=lambda ctx: True)
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.steps["a"].status, StepStatus.COMPLETED)

    def test_condition_reads_upstream_context(self):
        async def upstream(**kw):
            return {"proceed": True}

        wf = (WorkflowBuilder("cond")
              .step("a", "A", upstream)
              .step("b", "B", _noop, depends_on=["a"],
                    condition=lambda ctx: ctx.get("a.proceed") is True)
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.steps["b"].status, StepStatus.COMPLETED)


# ── Retry policy ──────────────────────────────────────────────────────────────────

class TestRetry(unittest.TestCase):
    def test_succeeds_after_transient_failures(self):
        wf = (WorkflowBuilder("retry")
              .step("a", "A", _fail_n_times(2),
                    retry=RetryPolicy(max_attempts=3, base_delay_s=0.01, max_delay_s=0.01))
              .build())
        result = run(get_workflow_engine().execute(wf))
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.steps["a"].attempt, 3)
        self.assertEqual(result.steps["a"].result["succeeded_on_attempt"], 3)

    def test_exhausts_retries_and_fails(self):
        wf = (WorkflowBuilder("retry-exhaust")
              .step("a", "A", _fail_always,
                    retry=RetryPolicy(max_attempts=2, base_delay_s=0.01, max_delay_s=0.01))
              .build())
        result = run(get_workflow_engine().execute(wf, saga=False))
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.steps["a"].status, StepStatus.FAILED)
        self.assertEqual(result.steps["a"].attempt, 2)
        self.assertIn("intentional failure", result.steps["a"].error)

    def test_exponential_backoff_delay_calculation(self):
        policy = RetryPolicy(base_delay_s=1.0, backoff=2.0, max_delay_s=30.0)
        self.assertEqual(policy.delay(1), 1.0)
        self.assertEqual(policy.delay(2), 2.0)
        self.assertEqual(policy.delay(3), 4.0)
        self.assertEqual(policy.delay(10), 30.0)  # capped at max_delay_s


# ── Timeout ───────────────────────────────────────────────────────────────────────

class TestTimeout(unittest.TestCase):
    def test_step_exceeding_timeout_fails(self):
        wf = (WorkflowBuilder("timeout")
              .step("a", "A", _slow, timeout_s=0.05,
                    retry=RetryPolicy(max_attempts=1))
              .build())
        result = run(get_workflow_engine().execute(wf, saga=False))
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.steps["a"].status, StepStatus.FAILED)


# ── Saga compensation ─────────────────────────────────────────────────────────────

class TestSagaCompensation(unittest.TestCase):
    def test_compensates_completed_steps_in_lifo_order_on_failure(self):
        compensated_order: list[str] = []

        def make_compensation(step_id: str):
            async def _comp(**kw):
                compensated_order.append(step_id)
            return _comp

        wf = (WorkflowBuilder("saga")
              .step("a", "A", _noop, compensation=make_compensation("a"))
              .step("b", "B", _noop, depends_on=["a"], compensation=make_compensation("b"))
              .step("c", "C", _fail_always, depends_on=["b"],
                    retry=RetryPolicy(max_attempts=1))
              .build())
        result = run(get_workflow_engine().execute(wf, saga=True))
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.steps["a"].status, StepStatus.COMPENSATED)
        self.assertEqual(result.steps["b"].status, StepStatus.COMPENSATED)
        # LIFO: b (started later) compensates before a
        self.assertEqual(compensated_order, ["b", "a"])

    def test_saga_false_skips_compensation(self):
        compensated = []
        async def comp(**kw):
            compensated.append("a")

        wf = (WorkflowBuilder("no-saga")
              .step("a", "A", _noop, compensation=comp)
              .step("b", "B", _fail_always, depends_on=["a"],
                    retry=RetryPolicy(max_attempts=1))
              .build())
        result = run(get_workflow_engine().execute(wf, saga=False))
        self.assertEqual(result.status, WorkflowStatus.FAILED)
        self.assertEqual(result.steps["a"].status, StepStatus.COMPLETED)  # not compensated
        self.assertEqual(compensated, [])

    def test_steps_without_compensation_fn_are_left_alone(self):
        wf = (WorkflowBuilder("partial-saga")
              .step("a", "A", _noop)  # no compensation_fn
              .step("b", "B", _fail_always, depends_on=["a"],
                    retry=RetryPolicy(max_attempts=1))
              .build())
        result = run(get_workflow_engine().execute(wf, saga=True))
        # 'a' has no compensation_fn, so it stays COMPLETED rather than COMPENSATED
        self.assertEqual(result.steps["a"].status, StepStatus.COMPLETED)


# ── Human approval gate ────────────────────────────────────────────────────────────

class TestApprovalGate(unittest.TestCase):
    def test_approved_step_completes(self):
        registry = ApprovalRegistry()

        async def go():
            wf = (WorkflowBuilder("approval")
                  .step("a", "A", _noop, requires_approval=True, timeout_s=2.0)
                  .build())
            approval_id = f"{wf.run_id}:a"

            async def approve_shortly():
                await asyncio.sleep(0.05)
                # patch the module-level registry the engine actually uses
                from app.core.workflow.engine import get_approval_registry
                get_approval_registry().approve(approval_id)

            asyncio.create_task(approve_shortly())
            return await get_workflow_engine().execute(wf)

        result = run(go())
        self.assertEqual(result.status, WorkflowStatus.COMPLETED)
        self.assertEqual(result.steps["a"].status, StepStatus.COMPLETED)

    def test_rejected_step_is_skipped(self):
        async def go():
            wf = (WorkflowBuilder("rejection")
                  .step("a", "A", _noop, requires_approval=True, timeout_s=2.0)
                  .build())
            approval_id = f"{wf.run_id}:a"

            async def reject_shortly():
                await asyncio.sleep(0.05)
                from app.core.workflow.engine import get_approval_registry
                get_approval_registry().reject(approval_id)

            asyncio.create_task(reject_shortly())
            return await get_workflow_engine().execute(wf)

        result = run(go())
        self.assertEqual(result.steps["a"].status, StepStatus.SKIPPED)
        self.assertEqual(result.steps["a"].error, "Rejected by approver")

    def test_approval_timeout_fails_step(self):
        wf = (WorkflowBuilder("approval-timeout")
              .step("a", "A", _noop, requires_approval=True, timeout_s=0.05)
              .build())
        result = run(get_workflow_engine().execute(wf, saga=False))
        self.assertEqual(result.steps["a"].status, StepStatus.FAILED)
        self.assertEqual(result.steps["a"].error, "Approval timeout")


class TestApprovalRegistry(unittest.TestCase):
    def test_register_approve_was_approved(self):
        reg = ApprovalRegistry()
        ev = reg.register("x:1")
        self.assertFalse(ev.is_set())
        reg.approve("x:1")
        self.assertTrue(ev.is_set())
        self.assertTrue(reg.was_approved("x:1"))

    def test_register_reject_was_approved_false(self):
        reg = ApprovalRegistry()
        reg.register("x:2")
        reg.reject("x:2")
        self.assertFalse(reg.was_approved("x:2"))

    def test_pending_lists_unset_events_only(self):
        reg = ApprovalRegistry()
        reg.register("x:3")
        reg.register("x:4")
        reg.approve("x:3")
        self.assertEqual(reg.pending(), ["x:4"])


# ── Event bus integration ──────────────────────────────────────────────────────────

class TestWorkflowEvents(unittest.TestCase):
    def test_success_publishes_started_then_completed(self):
        from app.core.events.bus import EventBus

        bus = EventBus()
        seen = []
        async def handler(e):
            seen.append(e.type)
        bus.subscribe("workflow.*", handler)

        async def go():
            import app.core.events as events_mod
            original = events_mod.get_event_bus
            events_mod.get_event_bus = lambda: bus
            try:
                wf = WorkflowBuilder("ev-success").step("a", "A", _noop).build()
                return await get_workflow_engine().execute(wf)
            finally:
                events_mod.get_event_bus = original

        run(go())
        self.assertEqual(seen, ["workflow.started", "workflow.completed"])

    def test_failure_publishes_started_then_failed(self):
        from app.core.events.bus import EventBus
        bus = EventBus()
        seen = []
        async def handler(e):
            seen.append(e.type)
        bus.subscribe("workflow.*", handler)

        async def go():
            import app.core.events as events_mod
            original = events_mod.get_event_bus
            events_mod.get_event_bus = lambda: bus
            try:
                wf = (WorkflowBuilder("ev-fail")
                      .step("a", "A", _fail_always, retry=RetryPolicy(max_attempts=1))
                      .build())
                return await get_workflow_engine().execute(wf, saga=False)
            finally:
                events_mod.get_event_bus = original

        run(go())
        self.assertEqual(seen, ["workflow.started", "workflow.failed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
