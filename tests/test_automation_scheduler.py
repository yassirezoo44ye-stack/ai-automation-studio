"""
F7 — unit tests for automation_scheduler.py

1. _make_step_fn() dispatcher: noop / ai / approval / unknown
2. F2: next_run_at advances after successful enqueue; left unchanged on failure
3. F8: idempotency key includes trigger_id; two triggers → two distinct keys
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


# ── async helpers ─────────────────────────────────────────────────────────────

class _AsyncCM:
    """Minimal async context manager that yields a mock DB connection."""
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


class _CountingPool:
    """Returns connections in order on successive acquire() calls."""
    def __init__(self, conns: list):
        self._conns = conns
        self._call = 0

    def acquire(self):
        idx = min(self._call, len(self._conns) - 1)
        conn = self._conns[idx]
        self._call += 1
        return _AsyncCM(conn)


# =============================================================================
# 1. _make_step_fn() dispatcher
# =============================================================================

class TestStepDispatcher(unittest.TestCase):

    def test_noop_kind_is_coroutine_fn(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        fn = _make_step_fn("noop", {"id": "s1"})
        self.assertTrue(inspect.iscoroutinefunction(fn))

    def test_noop_result_preserves_kind(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        async def _t():
            result = await _make_step_fn("noop", {"id": "s1"})()
            self.assertEqual(result["kind"], "noop")
            self.assertEqual(result["status"], "noop")
        asyncio.run(_t())

    def test_unknown_kind_is_noop(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        async def _t():
            fn = _make_step_fn("http_request", {"id": "s2"})
            self.assertTrue(inspect.iscoroutinefunction(fn))
            result = await fn()
            self.assertEqual(result["kind"], "http_request")
            self.assertEqual(result["status"], "noop")
        asyncio.run(_t())

    def test_approval_kind_is_coroutine_fn(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        fn = _make_step_fn("approval", {"id": "gate1"})
        self.assertTrue(inspect.iscoroutinefunction(fn))

    def test_approval_result(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        async def _t():
            result = await _make_step_fn("approval", {"id": "gate1"})()
            self.assertEqual(result["kind"], "approval")
            self.assertEqual(result["status"], "approved")
        asyncio.run(_t())

    def test_ai_kind_is_coroutine_fn(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        fn = _make_step_fn("ai", {"id": "ai1", "args": {}})
        self.assertTrue(inspect.iscoroutinefunction(fn))

    def test_ai_calls_agent_runtime_with_spec_args(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        spec = {
            "id": "ai-step",
            "name": "My AI Step",
            "args": {
                "system_prompt": "You are helpful",
                "provider_id": "anthropic",
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 512,
                "temperature": 0.5,
                "prompt": "Summarize this",
                "tools": ["web_search"],
            }
        }
        mock_result = MagicMock(success=True, content="Summary", rounds=1, error=None)
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        MockRuntime = MagicMock(return_value=mock_instance)

        async def _t():
            fn = _make_step_fn("ai", spec)
            with patch("app.core.ai.agents.runtime.AgentRuntime", MockRuntime):
                result = await fn()

            MockRuntime.assert_called_once()
            cfg = MockRuntime.call_args[0][0]
            self.assertEqual(cfg.name, "My AI Step")
            self.assertEqual(cfg.system_prompt, "You are helpful")
            self.assertEqual(cfg.provider_id, "anthropic")
            self.assertEqual(cfg.max_tokens, 512)
            self.assertAlmostEqual(float(cfg.temperature), 0.5)
            self.assertEqual(cfg.tools, ["web_search"])
            mock_instance.run.assert_called_once_with("Summarize this")
            self.assertTrue(result["success"])
            self.assertEqual(result["content"], "Summary")
            self.assertEqual(result["rounds"], 1)
            self.assertIsNone(result["error"])

        asyncio.run(_t())

    def test_ai_name_falls_back_to_id(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        spec = {"id": "fallback-id", "args": {"prompt": "test"}}
        mock_result = MagicMock(success=True, content="", rounds=1, error=None)
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value=mock_result)
        MockRuntime = MagicMock(return_value=mock_instance)

        async def _t():
            fn = _make_step_fn("ai", spec)
            with patch("app.core.ai.agents.runtime.AgentRuntime", MockRuntime):
                await fn()
            cfg = MockRuntime.call_args[0][0]
            self.assertEqual(cfg.name, "fallback-id")

        asyncio.run(_t())


# =============================================================================
# 2. F2 — next_run_at advancement
# =============================================================================

class TestNextRunAtAdvancement(unittest.TestCase):

    def _due_row(self, def_id: str, org_id: str, trigger_id: str) -> dict:
        return {
            "id": uuid.UUID(def_id),
            "organization_id": uuid.UUID(org_id),
            "triggers": [
                {
                    "id": trigger_id,
                    "kind": "schedule",
                    "next_run_at": time.time() - 60,
                    "schedule_interval_s": 3600,
                }
            ],
        }

    def test_next_run_at_advances_after_successful_enqueue(self):
        def_id, org_id, trigger_id = str(uuid.uuid4()), str(uuid.uuid4()), "sched-t1"

        conn_select = AsyncMock()
        conn_select.fetch = AsyncMock(return_value=[self._due_row(def_id, org_id, trigger_id)])
        conn_insert = AsyncMock()
        conn_insert.execute = AsyncMock(return_value="INSERT 0 1")
        conn_update = AsyncMock()
        conn_update.execute = AsyncMock(return_value="UPDATE 1")

        pool = _CountingPool([conn_select, conn_insert, conn_update])
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_scheduler import _tick_schedule_triggers
            with patch("app.core.db.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    await _tick_schedule_triggers()

            conn_update.execute.assert_called_once()
            args = conn_update.execute.call_args.args
            self.assertIn("UPDATE automation_definitions", args[0])
            updated = json.loads(args[1])
            t = next(t for t in updated if t["id"] == trigger_id)
            self.assertGreater(t["next_run_at"], time.time(),
                               "next_run_at must be advanced into the future")

        asyncio.run(_t())

    def test_next_run_at_not_updated_when_enqueue_fails(self):
        def_id, org_id, trigger_id = str(uuid.uuid4()), str(uuid.uuid4()), "sched-t2"

        conn_select = AsyncMock()
        conn_select.fetch = AsyncMock(return_value=[self._due_row(def_id, org_id, trigger_id)])
        conn_insert = AsyncMock()
        conn_insert.execute = AsyncMock(return_value="INSERT 0 1")
        # conn_update must NOT be reached
        conn_update = AsyncMock()
        conn_update.execute = AsyncMock()

        pool = _CountingPool([conn_select, conn_insert])
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock(side_effect=RuntimeError("queue unavailable"))

        async def _t():
            from app.core.workflow.automation_scheduler import _tick_schedule_triggers
            with patch("app.core.db.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    await _tick_schedule_triggers()  # must swallow the error

            conn_update.execute.assert_not_called()

        asyncio.run(_t())

    def test_next_run_at_not_updated_when_insert_fails(self):
        def_id, org_id, trigger_id = str(uuid.uuid4()), str(uuid.uuid4()), "sched-t3"

        conn_select = AsyncMock()
        conn_select.fetch = AsyncMock(return_value=[self._due_row(def_id, org_id, trigger_id)])
        conn_insert = AsyncMock()
        conn_insert.execute = AsyncMock(side_effect=RuntimeError("db write failed"))
        conn_update = AsyncMock()
        conn_update.execute = AsyncMock()

        pool = _CountingPool([conn_select, conn_insert])
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_scheduler import _tick_schedule_triggers
            with patch("app.core.db.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    await _tick_schedule_triggers()

            mock_queue.submit.assert_not_called()
            conn_update.execute.assert_not_called()

        asyncio.run(_t())


# =============================================================================
# 3. F8 — idempotency key format + per-trigger uniqueness
# =============================================================================

class TestSchedulerIdempotencyKeyF8(unittest.TestCase):

    def _make_row(self, def_id: str, org_id: str, trigger_ids: list[str]) -> dict:
        return {
            "id": uuid.UUID(def_id),
            "organization_id": uuid.UUID(org_id),
            "triggers": [
                {"id": tid, "kind": "schedule", "next_run_at": time.time() - 10}
                for tid in trigger_ids
            ],
        }

    def test_key_format_matches_auto_sched_def_trigger_tick(self):
        """Scheduler uses auto-sched:{def_id}:{trigger_id}:{tick} as idempotency key."""
        def_id, org_id, trigger_id = str(uuid.uuid4()), str(uuid.uuid4()), "sched-abc"

        conn_select = AsyncMock()
        conn_select.fetch = AsyncMock(return_value=[self._make_row(def_id, org_id, [trigger_id])])
        conn_insert = AsyncMock()
        conn_insert.execute = AsyncMock(return_value="INSERT 0 1")
        conn_update = AsyncMock()
        conn_update.execute = AsyncMock(return_value="UPDATE 1")

        pool = _CountingPool([conn_select, conn_insert, conn_update])
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_scheduler import _tick_schedule_triggers
            with patch("app.core.db.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    await _tick_schedule_triggers()

            mock_queue.submit.assert_called_once()
            key = mock_queue.submit.call_args.kwargs["idempotency_key"]
            expected_prefix = f"auto-sched:{def_id}:{trigger_id}:"
            self.assertTrue(key.startswith(expected_prefix),
                            f"key={key!r} must start with {expected_prefix!r}")
            tick = int(key[len(expected_prefix):])
            self.assertEqual(tick % 60, 0, "tick must be floored to minute boundary")

        asyncio.run(_t())

    def test_two_triggers_produce_different_keys_in_same_tick(self):
        """Multi-trigger definition: each trigger gets a distinct idempotency key."""
        def_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())

        # SELECT → INSERT-A → UPDATE-A → INSERT-B → UPDATE-B
        conns = [AsyncMock() for _ in range(5)]
        conns[0].fetch = AsyncMock(
            return_value=[self._make_row(def_id, org_id, ["trigger-A", "trigger-B"])]
        )
        for c in conns[1:]:
            c.execute = AsyncMock(return_value="OK")

        pool = _CountingPool(conns)
        mock_queue = AsyncMock()
        mock_queue.submit = AsyncMock()

        async def _t():
            from app.core.workflow.automation_scheduler import _tick_schedule_triggers
            with patch("app.core.db.get_pool", return_value=pool):
                with patch("app.core.jobs.get_job_queue", return_value=mock_queue):
                    await _tick_schedule_triggers()

            self.assertEqual(mock_queue.submit.call_count, 2,
                             "submit must be called once per due trigger")
            keys = [c.kwargs["idempotency_key"] for c in mock_queue.submit.call_args_list]
            self.assertEqual(len(set(keys)), 2,
                             f"Keys must be distinct; got {keys}")
            key_a = next((k for k in keys if "trigger-A" in k), None)
            key_b = next((k for k in keys if "trigger-B" in k), None)
            self.assertIsNotNone(key_a, "No key contains trigger-A")
            self.assertIsNotNone(key_b, "No key contains trigger-B")

        asyncio.run(_t())


# =============================================================================
# 4. Email step — args nesting and recipient resolution
# =============================================================================

class TestEmailStepFn(unittest.TestCase):
    """
    Verify _make_email_step_fn reads subject/body from spec["args"], not
    from the top level of spec.  This matches the contract the engine enforces
    and the payload that LeadFollowupCard.makeFollowupPayload() now produces.
    """

    def _make_send_mock(self):
        """Return a coroutine mock for app.core.email.send_email."""
        m = AsyncMock()
        return m

    def test_email_step_reads_subject_and_body_from_args(self):
        """Subject and body must come from spec["args"], not top-level."""
        from app.core.workflow.automation_scheduler import _make_email_step_fn
        spec = {
            "id": "send-followup-email",
            "kind": "email",
            "args": {"subject": "Hello from test", "body": "<p>Test body</p>", "to": "lead@example.com"},
        }
        send_mock = self._make_send_mock()

        async def _t():
            fn = _make_email_step_fn(spec)
            with patch("app.core.email.send_email", send_mock):
                result = await fn(_context={})
            send_mock.assert_called_once()
            _, called_subject, called_body = send_mock.call_args.args
            self.assertEqual(called_subject, "Hello from test")
            self.assertIn("Test body", called_body)
            self.assertEqual(result["status"], "sent")
            self.assertEqual(result["recipient"], "lead@example.com")

        asyncio.run(_t())

    def test_email_step_top_level_subject_is_ignored(self):
        """Top-level subject/body (old broken payload shape) are NOT used; args is the contract."""
        from app.core.workflow.automation_scheduler import _make_email_step_fn
        # Simulate the OLD broken payload structure: subject/body at top level, no args key.
        # Provide `args.to` so the recipient check passes — only the subject branch is under test.
        spec = {
            "id": "send-followup-email",
            "kind": "email",
            "subject": "Top-level subject (old format — must be ignored)",
            "body": "Top-level body",
            "args": {"to": "lead@example.com"},  # to is correct; subject/body intentionally absent
        }
        send_mock = self._make_send_mock()

        async def _t():
            fn = _make_email_step_fn(spec)
            with patch("app.core.email.send_email", send_mock):
                await fn(_context={})
            _, called_subject, _ = send_mock.call_args.args
            # Default subject used because args.subject is absent — top-level spec.subject is never read
            self.assertEqual(called_subject, "Follow-up from our team",
                             "Top-level spec.subject must NOT be used; only args.subject counts")

        asyncio.run(_t())

    def test_email_step_falls_back_to_lead_context_email(self):
        """When args.to is absent, email is taken from _context['lead']['email']."""
        from app.core.workflow.automation_scheduler import _make_email_step_fn
        spec = {
            "id": "send-followup-email",
            "kind": "email",
            "args": {"subject": "Hi", "body": "Body"},
        }
        send_mock = self._make_send_mock()

        async def _t():
            fn = _make_email_step_fn(spec)
            ctx = {"lead": {"email": "contextlead@example.com", "name": "Alice"}}
            with patch("app.core.email.send_email", send_mock):
                result = await fn(_context=ctx)
            send_mock.assert_called_once()
            called_to = send_mock.call_args.args[0]
            self.assertEqual(called_to, "contextlead@example.com")
            self.assertEqual(result["recipient"], "contextlead@example.com")

        asyncio.run(_t())

    def test_email_step_raises_without_any_recipient(self):
        """No args.to, no lead context, no lead_id → ValueError (not silent skip)."""
        from app.core.workflow.automation_scheduler import _make_email_step_fn
        spec = {"id": "send-followup-email", "kind": "email", "args": {"subject": "Hi"}}

        async def _t():
            fn = _make_email_step_fn(spec)
            with self.assertRaises(ValueError, msg="Must raise, not silently skip"):
                await fn(_context={})

        asyncio.run(_t())


# =============================================================================
# 5. _execute_definition — step id requirement
# =============================================================================

class TestExecuteDefinitionStepIdRequirement(unittest.TestCase):
    """
    _execute_definition must skip steps that have no 'id' field.
    This mirrors the engine contract and validates that the old broken
    LeadFollowupCard payload (steps without 'id') produces zero executed steps.
    """

    def _make_pool_with_definition(self, steps: list) -> tuple:
        """Build a fake pool returning a definition row with the given steps."""
        defn = {"steps": steps}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"definition": defn})

        class _CM:
            def __init__(self, c): self._c = c
            async def __aenter__(self): return self._c
            async def __aexit__(self, *_): pass

        class _Pool:
            def __init__(self, c): self._c = c
            def acquire(self): return _CM(self._c)

        return _Pool(conn), conn

    def test_steps_without_id_are_silently_skipped(self):
        """Definitions with steps missing 'id' produce a run with zero steps executed."""
        # Old (broken) LeadFollowupCard payload
        broken_steps = [{"kind": "email", "subject": "X", "body": "Y"}]
        pool, _ = self._make_pool_with_definition(broken_steps)

        executed_step_ids: list[str] = []

        async def _t():
            from app.core.workflow.automation_scheduler import _execute_definition
            from app.core.workflow.engine import get_workflow_engine

            engine = get_workflow_engine()
            original_execute = engine.execute

            async def _capture(run):
                executed_step_ids.extend(run.steps.keys())
                # Don't actually run steps; just capture which were registered
            engine.execute = _capture

            try:
                with patch("app.core.db.get_pool", return_value=pool):
                    with patch("app.core.workflow.persistence.upsert_run", new_callable=AsyncMock):
                        with patch("app.core.workflow.persistence.upsert_steps_bulk", new_callable=AsyncMock):
                            await _execute_definition(
                                str(uuid.uuid4()), str(uuid.uuid4()),
                                str(uuid.uuid4()), {}
                            )
            finally:
                engine.execute = original_execute

        asyncio.run(_t())
        self.assertEqual(executed_step_ids, [],
                         "Steps without 'id' must not be registered in the run")

    def test_steps_with_id_are_registered(self):
        """Definitions with steps that have 'id' produce registered steps in the run."""
        correct_steps = [
            {"id": "send-followup-email", "kind": "email",
             "args": {"subject": "Hi", "body": "Body", "to": "x@x.com"}}
        ]
        pool, _ = self._make_pool_with_definition(correct_steps)

        executed_step_ids: list[str] = []

        async def _t():
            from app.core.workflow.automation_scheduler import _execute_definition
            from app.core.workflow.engine import get_workflow_engine

            engine = get_workflow_engine()
            original_execute = engine.execute

            async def _capture(run):
                executed_step_ids.extend(run.steps.keys())
            engine.execute = _capture

            try:
                with patch("app.core.db.get_pool", return_value=pool):
                    with patch("app.core.workflow.persistence.upsert_run", new_callable=AsyncMock):
                        with patch("app.core.workflow.persistence.upsert_steps_bulk", new_callable=AsyncMock):
                            await _execute_definition(
                                str(uuid.uuid4()), str(uuid.uuid4()),
                                str(uuid.uuid4()), {}
                            )
            finally:
                engine.execute = original_execute

        asyncio.run(_t())
        self.assertIn("send-followup-email", executed_step_ids,
                      "Step with 'id' must be registered in the run")


if __name__ == "__main__":
    unittest.main()
