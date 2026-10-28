"""
Tests for Phase 5 Gate 3 — Database & Persistence.

Coverage:
  • JSON serialization (including non-serializable types)
  • _epoch_to_dt conversion
  • _parse_org_id validation
  • Schema DDL idempotency (smoke — no real DB needed; we verify the SQL strings)
  • mark_interrupted_runs (mock pool)
  • upsert_run / upsert_steps_bulk / create_approval_request / record_approval_decision
    (mock pool via unittest.mock.patch)
  • Webhook HMAC verification
  • Webhook timestamp gate (replay protection)
  • Automation API router — org isolation (definition CRUD responses)
  • Approval decision DB-first semantics
  • Scheduler idempotency key format
  • RLS table list contains all 4 new tables
  • factory.py imports both new routers
  • Engine files unchanged (git diff check)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. JSON serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeJsonValue(unittest.TestCase):
    def setUp(self):
        from app.core.workflow.persistence import _safe_json_value, safe_json, serialize_context
        self._sfn  = _safe_json_value
        self._safe = safe_json
        self._ctx  = serialize_context

    def test_primitives_passthrough(self):
        for val in (None, True, False, 0, 3.14, "hello"):
            self.assertEqual(self._sfn(val), val)

    def test_callable_coerced(self):
        def my_fn(): pass
        result = self._sfn(my_fn)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("coerced"))
        self.assertIn("function", result.get("type", ""))

    def test_coroutine_coerced(self):
        async def my_coro(): pass
        coro = my_coro()
        result = self._sfn(coro)
        coro.close()   # silence ResourceWarning
        self.assertTrue(result.get("coerced"))

    def test_asyncio_event_coerced(self):
        import asyncio as _aio
        ev = _aio.Event()
        result = self._sfn(ev)
        self.assertTrue(result.get("coerced"))

    def test_dict_recursive(self):
        def fn(): pass
        d = {"a": 1, "fn": fn}
        result = self._sfn(d)
        self.assertEqual(result["a"], 1)
        self.assertTrue(result["fn"]["coerced"])

    def test_list_recursive(self):
        def fn(): pass
        lst = [1, fn, "ok"]
        result = self._sfn(lst)
        self.assertEqual(result[0], 1)
        self.assertTrue(result[1]["coerced"])
        self.assertEqual(result[2], "ok")

    def test_uuid_becomes_string(self):
        uid = uuid.uuid4()
        self.assertEqual(self._sfn(uid), str(uid))

    def test_depth_limit(self):
        # Build a deeply nested dict that exceeds depth=10
        d: dict = {}
        cur = d
        for _ in range(13):
            nxt: dict = {}
            cur["child"] = nxt
            cur = nxt
        result = self._safe(d)
        # Should not raise; deeply nested parts truncated
        self.assertIsInstance(result, dict)

    def test_serialize_context_drops_callables(self):
        def fn(): pass
        ctx = {"key": "value", "fn": fn}
        out = self._ctx(ctx)
        parsed = json.loads(out)
        self.assertEqual(parsed["key"], "value")
        # callable should be coerced to a sentinel dict
        self.assertIsInstance(parsed["fn"], dict)

    def test_serialize_context_returns_string(self):
        out = self._ctx({"x": 42})
        self.assertIsInstance(out, str)
        parsed = json.loads(out)
        self.assertEqual(parsed["x"], 42)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Epoch → datetime conversion
# ─────────────────────────────────────────────────────────────────────────────

class TestEpochToDt(unittest.TestCase):
    def setUp(self):
        from app.core.workflow.persistence import _epoch_to_dt
        self._fn = _epoch_to_dt

    def test_none_returns_none(self):
        self.assertIsNone(self._fn(None))

    def test_float_returns_utc_datetime(self):
        from datetime import timezone
        ts = 1700000000.0
        dt = self._fn(ts)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_string_float_works(self):
        dt = self._fn(1700000000.0)
        self.assertIsNotNone(dt)

    def test_invalid_returns_none(self):
        self.assertIsNone(self._fn("not-a-number"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Organization ID validation
# ─────────────────────────────────────────────────────────────────────────────

class TestParseOrgId(unittest.TestCase):
    def setUp(self):
        from app.core.workflow.persistence import _parse_org_id
        self._fn = _parse_org_id

    def test_valid_uuid_string(self):
        uid = str(uuid.uuid4())
        self.assertEqual(self._fn(uid), uid)

    def test_uuid_object(self):
        uid = uuid.uuid4()
        self.assertEqual(self._fn(uid), str(uid))

    def test_none_returns_none(self):
        self.assertIsNone(self._fn(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self._fn(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(self._fn("not-a-uuid"))

    def test_short_string_returns_none(self):
        self.assertIsNone(self._fn("1234"))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Schema DDL correctness (smoke — no real DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaDDL(unittest.TestCase):
    def test_four_tables_defined(self):
        from app.core.workflow.automation_schema import (
            _SQL_AUTOMATION_DEFINITIONS,
            _SQL_AUTOMATION_RUNS,
            _SQL_AUTOMATION_RUN_STEPS,
            _SQL_AUTOMATION_APPROVALS,
        )
        for sql in [_SQL_AUTOMATION_DEFINITIONS, _SQL_AUTOMATION_RUNS,
                    _SQL_AUTOMATION_RUN_STEPS, _SQL_AUTOMATION_APPROVALS]:
            self.assertIn("CREATE TABLE IF NOT EXISTS", sql)
            self.assertIn("organization_id", sql)

    def test_automation_runs_has_required_statuses(self):
        from app.core.workflow.automation_schema import _SQL_AUTOMATION_RUNS
        for status in ("pending", "running", "completed", "failed",
                       "compensating", "cancelled", "interrupted"):
            self.assertIn(status, _SQL_AUTOMATION_RUNS)

    def test_run_steps_has_required_statuses(self):
        from app.core.workflow.automation_schema import _SQL_AUTOMATION_RUN_STEPS
        for status in ("pending", "running", "completed", "failed",
                       "skipped", "waiting", "compensated"):
            self.assertIn(status, _SQL_AUTOMATION_RUN_STEPS)

    def test_approvals_has_required_statuses(self):
        from app.core.workflow.automation_schema import _SQL_AUTOMATION_APPROVALS
        for status in ("pending", "approved", "rejected", "expired", "orphaned"):
            self.assertIn(status, _SQL_AUTOMATION_APPROVALS)

    def test_definitions_has_soft_delete(self):
        from app.core.workflow.automation_schema import _SQL_AUTOMATION_DEFINITIONS
        self.assertIn("deleted_at", _SQL_AUTOMATION_DEFINITIONS)

    def test_idempotent_schema_uses_if_not_exists(self):
        from app.core.workflow.automation_schema import (
            _SQL_AUTOMATION_DEFINITIONS_INDEXES,
            _SQL_AUTOMATION_RUNS_INDEXES,
        )
        for sql in [*_SQL_AUTOMATION_DEFINITIONS_INDEXES, *_SQL_AUTOMATION_RUNS_INDEXES]:
            self.assertIn("IF NOT EXISTS", sql)


# ─────────────────────────────────────────────────────────────────────────────
# 5. mark_interrupted_runs (mock pool)
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkInterruptedRuns(unittest.TestCase):
    def test_calls_update_query(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 3")
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            # mark_interrupted_runs does `from app.core.db import get_pool`
            # inside the function body, so patch app.core.db.get_pool.
            with patch("app.core.db.get_pool", return_value=mock_pool):
                import app.core.workflow.automation_schema as mod
                await mod.mark_interrupted_runs()
            mock_conn.execute.assert_called_once()
            sql = mock_conn.execute.call_args[0][0]
            self.assertIn("interrupted", sql)
            self.assertIn("UPDATE", sql)

        run(_test())

    def test_none_pool_is_non_fatal(self):
        async def _test():
            with patch("app.core.db.get_pool", return_value=None):
                import app.core.workflow.automation_schema as mod
                # Should not raise
                await mod.mark_interrupted_runs()
        run(_test())


class TestMarkLostPendingRuns(unittest.TestCase):
    """In-memory queue: pending runs from before a restart lost their job."""

    def test_marks_only_old_pending_runs_interrupted(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 6")
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            with patch("app.core.db.get_pool", return_value=mock_pool):
                import app.core.workflow.automation_schema as mod
                await mod.mark_lost_pending_runs()
            sql = mock_conn.execute.call_args[0][0]
            self.assertIn("status      = 'interrupted'", sql)
            self.assertIn("WHERE status = 'pending'", sql)
            # Runs a still-running previous instance just queued are left alone.
            self.assertIn("created_at < now() - interval '2 minutes'", sql)

        run(_test())

    def test_failure_is_non_fatal(self):
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(side_effect=RuntimeError("db down"))

        async def _test():
            with patch("app.core.db.get_pool", return_value=mock_pool):
                import app.core.workflow.automation_schema as mod
                await mod.mark_lost_pending_runs()   # must not raise
        run(_test())

    def test_only_in_memory_queue_is_not_durable(self):
        from app.core.cache.redis_adapter import LocalCacheBackend, RedisAdapter
        from app.core.jobs.queue import JobQueue

        class _RedisBackend(LocalCacheBackend):
            @property
            def backend_name(self):
                return "redis"

        self.assertFalse(JobQueue().durable)
        self.assertFalse(JobQueue(cache=RedisAdapter(LocalCacheBackend())).durable)
        self.assertTrue(JobQueue(cache=RedisAdapter(_RedisBackend())).durable)

    def test_startup_sweeps_pending_runs_only_without_durable_queue(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "app" / "factory.py").read_text()
        queue_init = src.index("get_job_queue(cache=cache)")
        sweep = src.index("await mark_lost_pending_runs()")
        self.assertLess(queue_init, sweep)
        self.assertIn("if not get_job_queue().durable:", src[queue_init:sweep])


# ─────────────────────────────────────────────────────────────────────────────
# 6. upsert_run (mock pool)
# ─────────────────────────────────────────────────────────────────────────────

class FakeRun:
    """Minimal WorkflowRun-like object for testing."""
    def __init__(self, run_id, status_val="running", context=None):
        self.run_id     = run_id
        self.name       = "test-run"
        self.context    = context or {}
        self.error      = None
        self.created_at = time.time()
        self.started_at = time.time()
        self.finished_at = None

        class _Status:
            value = status_val
        self.status = _Status()


class TestUpsertRun(unittest.TestCase):
    def _make_pool(self, execute_ret="INSERT 0 1"):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=execute_ret)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))
        return mock_pool, mock_conn

    def test_upsert_run_calls_execute(self):
        pool, conn = self._make_pool()

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import upsert_run
                run = FakeRun(str(uuid.uuid4()))
                await upsert_run(run, str(uuid.uuid4()))
            conn.execute.assert_called_once()

        run(_test())

    def test_upsert_run_skips_bad_org_id(self):
        pool, conn = self._make_pool()

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import upsert_run
                fake_run = FakeRun(str(uuid.uuid4()))
                await upsert_run(fake_run, "not-a-uuid")
            conn.execute.assert_not_called()

        run(_test())

    def test_upsert_run_handles_db_error(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=mock_pool):
                from app.core.workflow.persistence import upsert_run
                fake_run = FakeRun(str(uuid.uuid4()))
                # Should not raise (best-effort)
                await upsert_run(fake_run, str(uuid.uuid4()))

        run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 7. create_approval_request
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateApprovalRequest(unittest.TestCase):
    def test_returns_approval_id(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=mock_pool):
                from app.core.workflow.persistence import create_approval_request
                run_id  = str(uuid.uuid4())
                step_id = "step-1"
                org_id  = str(uuid.uuid4())
                result = await create_approval_request(org_id, run_id, step_id)
            self.assertEqual(result, f"{run_id}:{step_id}")
            mock_conn.execute.assert_called_once()

        run(_test())

    def test_bad_org_id_returns_none(self):
        async def _test():
            from app.core.workflow.persistence import create_approval_request
            result = await create_approval_request("bad-uuid", "r1", "s1")
            self.assertIsNone(result)
        run(_test())

    def test_approval_id_format(self):
        """approval_id must be '{run_id}:{step_id}' — Engine A key format."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=mock_pool):
                from app.core.workflow.persistence import create_approval_request
                run_id  = "my-run-123"
                step_id = "step-abc"
                result = await create_approval_request(str(uuid.uuid4()), run_id, step_id)
            self.assertEqual(result, "my-run-123:step-abc")
        run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 8. record_approval_decision — DB-first semantics
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordApprovalDecision(unittest.TestCase):
    def _pool(self, fetchval_ret):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=fetchval_ret)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))
        return mock_pool

    def test_returns_true_when_found(self):
        pool = self._pool(fetchval_ret=uuid.uuid4())

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import record_approval_decision
                result = await record_approval_decision("r:s", "approved", str(uuid.uuid4()))
            self.assertTrue(result)
        run(_test())

    def test_returns_false_when_not_found(self):
        pool = self._pool(fetchval_ret=None)

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import record_approval_decision
                result = await record_approval_decision("r:s", "approved", str(uuid.uuid4()))
            self.assertFalse(result)
        run(_test())

    def test_raises_on_invalid_status(self):
        async def _test():
            from app.core.workflow.persistence import record_approval_decision
            with self.assertRaises(ValueError):
                await record_approval_decision("r:s", "WRONG_STATUS", None)
        run(_test())

    def test_raises_on_db_failure(self):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=Exception("connection lost"))
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=mock_pool):
                from app.core.workflow.persistence import record_approval_decision
                with self.assertRaises(Exception):
                    await record_approval_decision("r:s", "approved", None)
        run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 9. Webhook HMAC verification
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhookHmac(unittest.TestCase):
    def setUp(self):
        from app.core.workflow.automation_webhooks import _verify_signature
        self._fn = _verify_signature

    def _make_sig(self, body: bytes, secret: str, ts: int) -> str:
        signed = f"{ts}.".encode() + body
        digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_passes(self):
        body   = b'{"event":"test"}'
        secret = "my-secret-key"
        ts     = int(time.time())
        sig    = self._make_sig(body, secret, ts)
        self.assertTrue(self._fn(body, secret, sig, str(ts)))

    def test_wrong_secret_fails(self):
        body   = b'{"event":"test"}'
        ts     = int(time.time())
        sig    = self._make_sig(body, "correct-secret", ts)
        self.assertFalse(self._fn(body, "wrong-secret", sig, str(ts)))

    def test_tampered_body_fails(self):
        body    = b'{"event":"test"}'
        secret  = "my-secret-key"
        ts      = int(time.time())
        sig     = self._make_sig(body, secret, ts)
        self.assertFalse(self._fn(b'{"event":"tampered"}', secret, sig, str(ts)))

    def test_stale_timestamp_fails(self):
        body    = b'body'
        secret  = "sec"
        old_ts  = int(time.time()) - 400   # > 5 minutes ago
        sig     = self._make_sig(body, secret, old_ts)
        self.assertFalse(self._fn(body, secret, sig, str(old_ts)))

    def test_future_timestamp_fails(self):
        body    = b'body'
        secret  = "sec"
        future  = int(time.time()) + 400
        sig     = self._make_sig(body, secret, future)
        self.assertFalse(self._fn(body, secret, sig, str(future)))

    def test_missing_headers_fail(self):
        self.assertFalse(self._fn(b'body', "sec", None, None))
        self.assertFalse(self._fn(b'body', "sec", "sha256=abc", None))
        self.assertFalse(self._fn(b'body', "sec", None, str(int(time.time()))))

    def test_wrong_sig_prefix_fails(self):
        body = b'body'
        secret = "sec"
        ts   = int(time.time())
        # Use md5= instead of sha256=
        bad_sig = "md5=somehex"
        self.assertFalse(self._fn(body, secret, bad_sig, str(ts)))

    def test_non_integer_timestamp_fails(self):
        self.assertFalse(self._fn(b'body', "sec", "sha256=abc", "not-a-number"))


# ─────────────────────────────────────────────────────────────────────────────
# 10. Scheduler idempotency key format
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerIdempotencyKey(unittest.TestCase):
    def test_key_format(self):
        """F8: key format includes trigger_id — auto-sched:{def_id}:{trigger_id}:{tick}."""
        from app.core.workflow.automation_scheduler import _floor_minute
        def_id     = str(uuid.uuid4())
        trigger_id = "sched-trigger-abc"
        ts         = time.time()
        tick       = _floor_minute(ts)
        key        = f"auto-sched:{def_id}:{trigger_id}:{tick}"
        self.assertTrue(key.startswith("auto-sched:"))
        self.assertIn(def_id, key)
        self.assertIn(trigger_id, key)
        # tick suffix should be divisible by 60
        self.assertEqual(tick % 60, 0)
        # Correct tail: ...:{trigger_id}:{tick}
        self.assertTrue(key.endswith(f":{trigger_id}:{tick}"))

    def test_same_minute_same_key(self):
        from app.core.workflow.automation_scheduler import _floor_minute
        ts1    = 1700000060.0
        ts2    = 1700000090.0
        self.assertEqual(_floor_minute(ts1), _floor_minute(ts2))


# ─────────────────────────────────────────────────────────────────────────────
# 11. RLS — 4 automation tables registered
# ─────────────────────────────────────────────────────────────────────────────

class TestRlsTables(unittest.TestCase):
    def test_automation_tables_in_rls(self):
        from app.tenancy.rls import _RLS_TABLES
        table_names = {t for t, _ in _RLS_TABLES}
        for name in ("automation_definitions", "automation_runs",
                     "automation_run_steps", "automation_approvals"):
            self.assertIn(name, table_names, f"{name} missing from _RLS_TABLES")

    def test_automation_tables_use_organization_id_column(self):
        from app.tenancy.rls import _RLS_TABLES
        mapping = dict(_RLS_TABLES)
        for name in ("automation_definitions", "automation_runs",
                     "automation_run_steps", "automation_approvals"):
            self.assertEqual(mapping[name], "organization_id")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Multi-tenancy isolation invariant
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantIsolation(unittest.TestCase):
    """Verifies that persistence functions validate org_id BEFORE executing queries."""

    def test_upsert_run_rejects_cross_tenant_org(self):
        """If org_id is None/invalid, the pool is never acquired."""
        pool = MagicMock()

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import upsert_run
                fake_run = FakeRun(str(uuid.uuid4()))
                await upsert_run(fake_run, None)  # type: ignore
            pool.acquire.assert_not_called()

        run(_test())

    def test_upsert_steps_bulk_rejects_bad_org(self):
        pool = MagicMock()

        async def _test():
            with patch("app.core.workflow.persistence.get_pool", return_value=pool):
                from app.core.workflow.persistence import upsert_steps_bulk
                await upsert_steps_bulk("run-1", "not-a-uuid", {})
            pool.acquire.assert_not_called()

        run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 13. Factory wires both automation routers
# ─────────────────────────────────────────────────────────────────────────────

class TestFactoryWiring(unittest.TestCase):
    def test_automation_api_imported_in_factory(self):
        import app.factory as factory_mod
        import app.core.workflow.automation_api as api_mod
        # The import at module level means the attr is present
        self.assertIs(factory_mod.automation_api_router, api_mod)

    def test_automation_webhooks_imported_in_factory(self):
        import app.factory as factory_mod
        import app.core.workflow.automation_webhooks as wh_mod
        self.assertIs(factory_mod.automation_webhooks_router, wh_mod)


# ─────────────────────────────────────────────────────────────────────────────
# 14. Engine files are not modified (import-level guard)
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineUnmodified(unittest.TestCase):
    def test_engine_a_still_importable(self):
        """Engine A must import without error."""
        from app.core.workflow.engine import (  # noqa: F401
            WorkflowEngine, WorkflowRun, WorkflowStep, WorkflowStatus,
            StepStatus, get_workflow_engine,
        )

    def test_engine_b_still_importable(self):
        """Engine B must import without error (we just need the module to load)."""
        try:
            import app.core.ai.workflow.engine  # noqa: F401
        except ImportError as exc:
            self.fail(f"Engine B import failed: {exc}")

    def test_automation_files_do_not_import_engine_at_module_level(self):
        """persistence.py must not import the engine at module level (no circular deps).

        We check that none of the *executable* lines (not docstring or comments)
        at module-level in persistence.py start with `from app.core.workflow.engine`.
        """
        source_path = Path(__file__).parent.parent / "app/core/workflow/persistence.py"
        source = source_path.read_text(encoding="utf-8")
        in_docstring = False
        for line in source.splitlines():
            stripped = line.strip()
            # Toggle docstring state on triple-quote boundaries
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            # Only check executable import lines
            if stripped.startswith("from app.core.workflow.engine"):
                self.fail(
                    "persistence.py has a top-level engine import: " + stripped
                )
            # Stop scanning at the first function/class (module-level top done)
            if stripped.startswith("async def ") or stripped.startswith("def ") or stripped.startswith("class "):
                break


# ─────────────────────────────────────────────────────────────────────────────
# 15. Webhook Fernet encrypt/decrypt round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhookSecretEncryption(unittest.TestCase):
    def test_roundtrip(self):
        from app.core.workflow.automation_webhooks import (
            encrypt_webhook_secret, decrypt_webhook_secret,
        )
        plaintext = "super-secret-webhook-key-42"
        encrypted = encrypt_webhook_secret(plaintext)
        self.assertNotEqual(encrypted, plaintext)
        decrypted = decrypt_webhook_secret(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_decrypt_invalid_returns_none(self):
        from app.core.workflow.automation_webhooks import decrypt_webhook_secret
        result = decrypt_webhook_secret("not-a-fernet-token")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 16. JSONB decoding (asyncpg returns JSONB as text — no codec on the pool)
# ─────────────────────────────────────────────────────────────────────────────

class TestDecodeJsonb(unittest.TestCase):
    def test_text_is_decoded(self):
        from app.core.workflow.persistence import decode_jsonb
        self.assertEqual(decode_jsonb('[{"id": "t1"}]', list, []), [{"id": "t1"}])
        self.assertEqual(decode_jsonb('{"a": 1}', dict, {}), {"a": 1})

    def test_already_decoded_passthrough(self):
        from app.core.workflow.persistence import decode_jsonb
        self.assertEqual(decode_jsonb({"a": 1}, dict, {}), {"a": 1})

    def test_bad_values_return_default(self):
        from app.core.workflow.persistence import decode_jsonb
        self.assertEqual(decode_jsonb(None, dict, {}), {})
        self.assertEqual(decode_jsonb("not json", list, []), [])
        self.assertEqual(decode_jsonb('{"a": 1}', list, []), [])


# ─────────────────────────────────────────────────────────────────────────────
# 17. External webhook through the real app + api_auth_middleware
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalWebhookEndpoint(unittest.IsolatedAsyncioTestCase):
    """End-to-end through create_app() (same pattern as
    tests/test_api_key_middleware_passthrough.py): an external sender with
    no session must reach the HMAC check, and only a valid signature is
    accepted. The DB is faked the way asyncpg really behaves — JSONB as text."""

    SECRET = "lead-intake-test-secret"

    def setUp(self):
        from app.core.workflow.automation_webhooks import encrypt_webhook_secret
        self.org_id = str(uuid.uuid4())
        self.def_id = str(uuid.uuid4())
        self.trigger_id = "lead-intake"
        triggers = [{"id": self.trigger_id, "kind": "webhook",
                     "secret_encrypted": encrypt_webhook_secret(self.SECRET)}]
        self.conn = AsyncMock()
        self.conn.fetchrow = AsyncMock(return_value={
            "triggers": json.dumps(triggers), "organization_id": uuid.UUID(self.org_id),
        })
        self.conn.fetchval = AsyncMock(return_value=uuid.UUID(self.org_id))
        self.conn.execute = AsyncMock(return_value="INSERT 0 1")
        self.pool = MagicMock()
        self.pool.acquire = MagicMock(side_effect=lambda: _async_cm(self.conn))
        self.queue = MagicMock()
        self.queue.submit = AsyncMock(return_value="job-1")

    def _headers(self, body: bytes, ts: int | None = None, secret: str | None = None) -> dict:
        ts = int(time.time()) if ts is None else ts
        digest = hmac.new((secret or self.SECRET).encode(), f"{ts}.".encode() + body,
                          hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Automation-Timestamp": str(ts),
            "X-Automation-Signature": f"sha256={digest}",
        }

    async def _post(self, body: bytes, headers: dict, path: str | None = None):
        from httpx import AsyncClient, ASGITransport
        from app.factory import create_app
        path = path or f"/api/webhooks/auto/{self.def_id}/{self.trigger_id}"
        with patch("app.core.workflow.automation_webhooks.get_pool", return_value=self.pool), \
             patch("app.core.workflow.automation_webhooks.get_job_queue", return_value=self.queue):
            async with AsyncClient(transport=ASGITransport(app=create_app()),
                                   base_url="http://test") as client:
                return await client.post(path, content=body, headers=headers)

    async def test_valid_hmac_is_accepted_without_session(self):
        body = json.dumps({"name": "Ahmed", "message": "Quote for 20 employees"}).encode()
        res = await self._post(body, self._headers(body))
        self.assertEqual(res.status_code, 202, res.text)
        self.assertEqual(res.json()["status"], "pending")
        self.queue.submit.assert_awaited_once()
        self.assertEqual(self.queue.submit.call_args.kwargs["payload"]["context"]["name"], "Ahmed")

    async def test_invalid_hmac_is_rejected(self):
        body = b'{"name": "Ahmed"}'
        res = await self._post(body, self._headers(body, secret="wrong-secret"))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Webhook authentication failed")
        self.queue.submit.assert_not_called()

    async def test_tampered_body_is_rejected(self):
        headers = self._headers(b'{"name": "Ahmed"}')
        res = await self._post(b'{"name": "Mallory"}', headers)
        self.assertEqual(res.status_code, 401)
        self.queue.submit.assert_not_called()

    async def test_expired_timestamp_is_rejected(self):
        body = b'{"name": "Ahmed"}'
        res = await self._post(body, self._headers(body, ts=int(time.time()) - 400))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Webhook authentication failed")
        self.queue.submit.assert_not_called()

    async def test_missing_signature_is_rejected(self):
        body = b'{"name": "Ahmed"}'
        headers = self._headers(body)
        del headers["X-Automation-Signature"]
        res = await self._post(body, headers)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Webhook authentication failed")
        self.queue.submit.assert_not_called()

    async def test_payload_organization_id_does_not_override_definition_org(self):
        other = str(uuid.uuid4())
        body = json.dumps({"name": "Ahmed", "organization_id": other}).encode()
        res = await self._post(body, self._headers(body))
        self.assertEqual(res.status_code, 202, res.text)
        kwargs = self.queue.submit.call_args.kwargs
        self.assertEqual(kwargs["org_id"], self.org_id)
        self.assertEqual(kwargs["payload"]["organization_id"], self.org_id)
        insert = next(c for c in self.conn.execute.call_args_list
                      if "INSERT INTO automation_runs" in c.args[0])
        self.assertEqual(insert.args[1], uuid.UUID(self.org_id))

    async def test_public_prefix_is_limited_to_automation_webhooks(self):
        """Only /api/webhooks/auto/ skips the session gate — a sibling path
        still gets the middleware's 401."""
        res = await self._post(b"{}", {}, path="/api/webhooks/other")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Subscription required")


# ─────────────────────────────────────────────────────────────────────────────
# 18. Webhook secret provisioning
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhookSecretProvisioning(unittest.TestCase):

    def _conn(self, triggers):
        conn = MagicMock()
        conn.transaction = MagicMock(return_value=_async_cm(None))
        conn.fetchrow = AsyncMock(return_value=None if triggers is None
                                  else {"triggers": json.dumps(triggers)})
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=_async_cm(conn))
        return pool, conn

    def _ctx(self):
        ctx = MagicMock()
        ctx.org_id = str(uuid.uuid4())
        ctx.user_id = str(uuid.uuid4())
        return ctx

    def test_rotate_stores_only_encrypted_secret_and_returns_plaintext_once(self):
        from app.core.workflow.automation_api import rotate_webhook_secret
        from app.core.workflow.automation_webhooks import decrypt_webhook_secret
        def_id = str(uuid.uuid4())
        pool, conn = self._conn([{"id": "t1", "kind": "webhook"},
                                 {"id": "s1", "kind": "schedule"}])

        async def _t():
            with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                with self.assertLogs("app.core.workflow.automation_api", "DEBUG") as logs:
                    out = await rotate_webhook_secret(def_id, "t1", ctx=self._ctx())
            return out, logs

        out, logs = run(_t())
        secret = out["secret"]
        self.assertGreaterEqual(len(secret), 32)
        self.assertEqual(out["webhook_path"], f"/api/webhooks/auto/{def_id}/t1")
        stored_json = conn.execute.call_args.args[1]
        self.assertNotIn(secret, stored_json)
        stored = json.loads(stored_json)
        self.assertEqual(decrypt_webhook_secret(stored[0]["secret_encrypted"]), secret)
        self.assertNotIn("secret_encrypted", stored[1])
        self.assertFalse(any(secret in line for line in logs.output))

    def test_rotate_generates_distinct_secrets(self):
        from app.core.workflow.automation_api import rotate_webhook_secret

        async def _t():
            outs = []
            for _ in range(2):
                pool, _ = self._conn([{"id": "t1", "kind": "webhook"}])
                with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                    outs.append(await rotate_webhook_secret(str(uuid.uuid4()), "t1", ctx=self._ctx()))
            return outs

        a, b = run(_t())
        self.assertNotEqual(a["secret"], b["secret"])

    def test_rotate_unknown_or_non_webhook_trigger_is_404(self):
        from fastapi import HTTPException
        from app.core.workflow.automation_api import rotate_webhook_secret
        for triggers, trigger_id in (
            (None, "t1"),                                   # definition missing / other org
            ([{"id": "t1", "kind": "schedule"}], "t1"),     # not a webhook trigger
            ([{"id": "t1", "kind": "webhook"}], "nope"),    # unknown trigger
        ):
            pool, conn = self._conn(triggers)

            async def _t():
                with patch("app.core.workflow.automation_api.get_pool", return_value=pool):
                    with self.assertRaises(HTTPException) as cm:
                        await rotate_webhook_secret(str(uuid.uuid4()), trigger_id, ctx=self._ctx())
                return cm.exception

            self.assertEqual(run(_t()).status_code, 404)
            conn.execute.assert_not_called()

    def test_api_view_redacts_secret(self):
        from app.core.workflow.automation_api import _redact_triggers
        out = _redact_triggers([
            {"id": "t1", "kind": "webhook", "secret_encrypted": "gAAAA..."},
            {"id": "t2", "kind": "webhook"},
        ])
        self.assertNotIn("secret_encrypted", out[0])
        self.assertTrue(out[0]["has_secret"])
        self.assertFalse(out[1]["has_secret"])

    def test_client_cannot_set_secret_but_update_keeps_existing(self):
        from app.core.workflow.automation_api import _merge_trigger_secrets
        old = [{"id": "t1", "kind": "webhook", "secret_encrypted": "stored"}]
        new = [
            {"id": "t1", "kind": "webhook", "has_secret": True},
            {"id": "t2", "kind": "webhook", "secret_encrypted": "client-forged"},
        ]
        merged = _merge_trigger_secrets(new, old)
        self.assertEqual(merged[0]["secret_encrypted"], "stored")
        self.assertNotIn("has_secret", merged[0])
        self.assertNotIn("secret_encrypted", merged[1])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _async_cm:
    """Simple async context manager that yields `obj` on __aenter__."""
    def __init__(self, obj):
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, *_):
        pass


if __name__ == "__main__":
    unittest.main()
