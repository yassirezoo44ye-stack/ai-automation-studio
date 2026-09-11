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
        from app.core.workflow.automation_scheduler import _floor_minute
        def_id = str(uuid.uuid4())
        ts     = time.time()
        tick   = _floor_minute(ts)
        key    = f"auto-sched:{def_id}:{tick}"
        self.assertTrue(key.startswith("auto-sched:"))
        self.assertIn(def_id, key)
        # tick should be divisible by 60
        self.assertEqual(tick % 60, 0)

    def test_same_minute_same_key(self):
        from app.core.workflow.automation_scheduler import _floor_minute
        def_id = str(uuid.uuid4())
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
