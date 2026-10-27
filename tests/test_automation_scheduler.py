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


def _mock_gateway(content: str):
    """Patch target for app.ai.gateway.AIGateway: AIGateway(pool).complete()
    returns a response whose .content is `content`. The instance is exposed
    as `.instance` for call assertions."""
    instance = MagicMock()
    instance.complete = AsyncMock(return_value=MagicMock(content=content))
    gateway_cls = MagicMock(return_value=instance)
    gateway_cls.instance = instance
    return gateway_cls


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

    def test_ai_calls_gateway_with_spec_args(self):
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
            }
        }
        org_id = str(uuid.uuid4())
        gw = _mock_gateway("Summary")

        async def _t():
            fn = _make_step_fn("ai", spec)
            with patch("app.ai.gateway.AIGateway", gw), \
                 patch("app.core.db.get_pool", return_value=MagicMock()):
                result = await fn(_context={"organization_id": org_id}, _run_id="r1")

            req = gw.instance.complete.call_args[0][0]
            self.assertEqual(req.system, "You are helpful")
            self.assertEqual(req.provider, "anthropic")
            self.assertEqual(req.model, "claude-haiku-4-5-20251001")
            self.assertEqual(req.max_tokens, 512)
            self.assertAlmostEqual(float(req.temperature), 0.5)
            self.assertEqual(req.messages[0].content, "Summarize this")
            self.assertEqual(result["content"], "Summary")

        asyncio.run(_t())

    def test_ai_with_tools_fails_explicitly(self):
        """AIGateway runs one completion — a tools spec must fail, not be ignored."""
        from app.core.workflow.automation_scheduler import _make_step_fn
        spec = {"id": "ai1", "args": {"prompt": "x", "tools": ["web_search"]}}
        gw = _mock_gateway("unused")

        async def _t():
            fn = _make_step_fn("ai", spec)
            with patch("app.ai.gateway.AIGateway", gw):
                with self.assertRaises(ValueError):
                    await fn(_context={"organization_id": str(uuid.uuid4())})
            gw.instance.complete.assert_not_called()

        asyncio.run(_t())

    def test_ai_without_org_context_fails(self):
        from app.core.workflow.automation_scheduler import _make_step_fn
        gw = _mock_gateway("unused")

        async def _t():
            fn = _make_step_fn("ai", {"id": "ai1", "args": {"prompt": "x"}})
            with patch("app.ai.gateway.AIGateway", gw):
                with self.assertRaises(ValueError):
                    await fn(_context={})
            gw.instance.complete.assert_not_called()

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


# =============================================================================
# 6. Lead Intake — context isolation, run status, AI classification, approvals
# =============================================================================

_LEAD = {
    "name": "Ahmed",
    "email": "ahmed@example.com",
    "phone": "+971500000000",
    "message": "I need a quotation for 20 employees",
    "source": "website",
}


def _definition_pool(definition: dict):
    """Pool whose fetchrow returns the definition as asyncpg really does:
    JSONB as raw text (no codec is registered on the app's pool)."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"definition": json.dumps(definition)})
    conn.execute = AsyncMock(return_value="UPDATE 1")
    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=lambda: _AsyncCM(conn))
    return pool, conn


def _persistence_patches():
    return (
        patch("app.core.workflow.persistence.upsert_run", new=AsyncMock()),
        patch("app.core.workflow.persistence.upsert_steps_bulk", new=AsyncMock()),
        patch("app.core.workflow.persistence.create_approval_request", new=AsyncMock()),
    )


def _final_status_update(conn) -> tuple:
    """(status, error) written by the handler's final UPDATE."""
    for c in conn.execute.call_args_list:
        if "SET status=$2" in c.args[0]:
            return c.args[2], c.args[3]
    raise AssertionError("final status UPDATE not issued")


class TestRunContextIsolation(unittest.TestCase):

    def test_payload_cannot_override_identity_keys(self):
        from app.core.workflow.automation_scheduler import _build_run_context
        org, other, def_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        payload = {
            **_LEAD,
            "organization_id": other, "org_id": other,
            "definition_id": str(uuid.uuid4()), "triggered_by_user": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()), "run_id": "spoofed", "trigger": {"x": 1},
        }
        ctx = _build_run_context(payload, org_id=org, definition_id=def_id,
                                 triggered_by="webhook")
        self.assertEqual(ctx["organization_id"], org)
        self.assertEqual(ctx["definition_id"], def_id)
        self.assertEqual(ctx["triggered_by"], "webhook")
        for key in ("org_id", "triggered_by_user", "user_id", "run_id"):
            self.assertNotIn(key, ctx)
        self.assertEqual(ctx["trigger"], _LEAD)
        self.assertEqual(ctx["message"], _LEAD["message"])

    def test_non_dict_payload_is_ignored(self):
        from app.core.workflow.automation_scheduler import _build_run_context
        org = str(uuid.uuid4())
        ctx = _build_run_context(["not", "a", "dict"], org_id=org, definition_id="d")
        self.assertEqual(ctx["organization_id"], org)
        self.assertEqual(ctx["trigger"], {})


class TestRunStatus(unittest.TestCase):

    def _job(self, org_id, context=None):
        return {
            "organization_id": org_id,
            "run_id": str(uuid.uuid4()),
            "definition_id": str(uuid.uuid4()),
            "context": context or {},
            "triggered_by": "webhook",
        }

    def test_successful_run_is_completed(self):
        from app.core.workflow.automation_scheduler import _handle_automation_run
        pool, conn = _definition_pool({"steps": [{"id": "s1", "kind": "noop"}]})
        p1, p2, p3 = _persistence_patches()

        async def _t():
            with patch("app.core.db.get_pool", return_value=pool), p1, p2, p3:
                await _handle_automation_run(self._job(str(uuid.uuid4())))

        asyncio.run(_t())
        status, error = _final_status_update(conn)
        self.assertEqual(status, "completed")
        self.assertIsNone(error)

    def test_failed_step_marks_run_failed(self):
        """A step failure inside the engine must persist 'failed', never the
        old unconditional 'completed'. Uses malformed AI output end-to-end."""
        from app.core.workflow.automation_scheduler import _handle_automation_run
        pool, conn = _definition_pool({"steps": [
            {"id": "classify", "kind": "ai", "args": {"output": "lead_classification"}},
        ]})
        gw = _mock_gateway("Sure! This lead looks hot.")
        p1, p2, p3 = _persistence_patches()

        async def _t():
            with patch("app.core.db.get_pool", return_value=pool), p1, p2, p3, \
                 patch("app.ai.gateway.AIGateway", gw):
                await _handle_automation_run(self._job(str(uuid.uuid4()), dict(_LEAD)))

        asyncio.run(_t())
        status, error = _final_status_update(conn)
        self.assertEqual(status, "failed")
        self.assertIn("classify", error)

    def test_definition_loaded_from_jsonb_text(self):
        """The definition column arrives as text; its steps must still run."""
        from app.core.workflow.automation_scheduler import _execute_definition
        pool, _ = _definition_pool({"steps": [{"id": "s1", "kind": "noop"}]})
        p1, p2, p3 = _persistence_patches()

        async def _t():
            with patch("app.core.db.get_pool", return_value=pool), p1, p2, p3:
                return await _execute_definition(
                    str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), {})

        run = asyncio.run(_t())
        self.assertEqual(run.status.value, "completed")
        self.assertEqual(run.steps["s1"].status.value, "completed")


class TestLeadClassificationStep(unittest.TestCase):

    _SPEC = {"id": "classify", "kind": "ai", "args": {"output": "lead_classification"}}

    def _ctx(self, org_id):
        from app.core.workflow.automation_scheduler import _build_run_context
        return _build_run_context(dict(_LEAD), org_id=org_id, definition_id="d",
                                  triggered_by="webhook")

    def _run_step(self, content, org_id=None):
        from app.core.workflow.automation_scheduler import _make_step_fn
        org_id = org_id or str(uuid.uuid4())
        gw = _mock_gateway(content)

        async def _t():
            fn = _make_step_fn("ai", self._SPEC)
            with patch("app.ai.gateway.AIGateway", gw), \
                 patch("app.core.db.get_pool", return_value=MagicMock()):
                return await fn(**self._SPEC["args"], _context=self._ctx(org_id), _run_id="r")

        return asyncio.run(_t()), gw

    def test_lead_payload_reaches_prompt(self):
        _, gw = self._run_step('{"tier": "hot", "score": 90, "reason": "Budget and size"}')
        prompt = gw.instance.complete.call_args[0][0].messages[0].content
        for value in _LEAD.values():
            self.assertIn(value, prompt)

    def test_gateway_called_with_run_org(self):
        org = str(uuid.uuid4())
        _, gw = self._run_step('{"tier": "hot", "score": 90, "reason": "r"}', org_id=org)
        self.assertEqual(gw.instance.complete.call_args.kwargs["org_id"], org)

    def test_valid_classification_is_returned(self):
        result, _ = self._run_step(
            '```json\n{"tier": "HOT", "score": 87, "reason": " Wants 20 seats "}\n```')
        self.assertEqual(result["tier"], "hot")
        self.assertEqual(result["score"], 87)
        self.assertEqual(result["reason"], "Wants 20 seats")

    def test_malformed_classification_raises(self):
        bad = [
            "This lead is hot.",
            "[1, 2, 3]",
            '{"tier": "boiling", "score": 50, "reason": "r"}',
            '{"tier": "hot", "score": 150, "reason": "r"}',
            '{"tier": "hot", "score": -1, "reason": "r"}',
            '{"tier": "hot", "score": "90", "reason": "r"}',
            '{"tier": "hot", "score": 90.5, "reason": "r"}',
            '{"tier": "hot", "score": true, "reason": "r"}',
            '{"tier": "hot", "score": 90, "reason": ""}',
            '{"tier": "hot", "score": 90}',
        ]
        for content in bad:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    self._run_step(content)


class TestApprovalOwnershipAfterContextFix(unittest.TestCase):

    def test_approval_requires_run_org_and_resumes_run(self):
        from app.core.workflow.automation_scheduler import _execute_definition
        from app.core.workflow.engine import get_workflow_engine
        org, other = str(uuid.uuid4()), str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        pool, _ = _definition_pool({"steps": [
            {"id": "gate", "kind": "approval", "requires_approval": True},
        ]})
        p1, p2, p3 = _persistence_patches()
        engine = get_workflow_engine()

        async def _t():
            with patch("app.core.db.get_pool", return_value=pool), p1, p2, p3:
                task = asyncio.create_task(_execute_definition(
                    org, run_id, str(uuid.uuid4()), {"organization_id": other}))
                approval_id = f"{run_id}:gate"
                for _ in range(200):
                    if approval_id in engine.pending_approvals(org_id=org):
                        break
                    await asyncio.sleep(0.01)
                self.assertIn(approval_id, engine.pending_approvals(org_id=org))
                self.assertNotIn(approval_id, engine.pending_approvals(org_id=other))
                self.assertFalse(engine.approve(run_id, "gate", org_id=other))
                self.assertTrue(engine.approve(run_id, "gate", org_id=org))
                return await asyncio.wait_for(task, timeout=5)

        run = asyncio.run(_t())
        self.assertEqual(run.status.value, "completed")
        self.assertEqual(run.context["organization_id"], org)


if __name__ == "__main__":
    unittest.main()
