"""
Generic idempotency layer (app/core/idempotency.py) — unit tests against a
mocked asyncpg pool (matching the plan's own "mocked pool/get_redis"
convention). The real app.core.cache module is used as-is (not mocked) —
with no REDIS_URL set in the test environment it transparently falls back
to LocalCacheBackend, so this genuinely exercises the fast-path cache read
without needing a live Redis. Each test uses a distinct scope so the
module-level cache singleton can't leak state between tests.
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.idempotency import IdempotencyInProgress, idempotent


def _norm(q: str) -> str:
    return " ".join(q.split())


class FakeIdempotencyPool:
    """In-memory stand-in for asyncpg.Pool, covering idempotent()'s query
    shapes: INSERT..ON CONFLICT..RETURNING id, SELECT status/result/age_s,
    and the three UPDATE variants (pending-reset / failed / completed).

    Each row carries an `age_s` a test can control directly (real Postgres
    computes this from created_at via now() - created_at) — new rows
    default to 0 ("just claimed"); mark_stale() simulates a row old enough
    to be treated as an abandoned/crashed attempt rather than one still
    genuinely in flight.
    """

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def mark_stale(self, scope: str, key: str) -> None:
        from app.core.idempotency import _STALE_PENDING_S
        self.rows[(scope, key)]["age_s"] = _STALE_PENDING_S + 1

    async def fetchrow(self, query, *args):
        q = _norm(query)
        if q.startswith("INSERT INTO idempotency_keys"):
            scope, key = args
            if (scope, key) in self.rows:
                return None
            self.rows[(scope, key)] = {
                "status": "pending", "result": None, "error": None, "age_s": 0,
            }
            return {"id": "fake-id"}
        if q.startswith("SELECT status, result,"):
            scope, key = args
            row = self.rows.get((scope, key))
            if row is None:
                return None
            return {"status": row["status"], "result": row["result"], "age_s": row["age_s"]}
        raise AssertionError(f"unexpected fetchrow query: {query!r}")

    async def execute(self, query, *args):
        q = _norm(query)
        if not q.startswith("UPDATE idempotency_keys"):
            raise AssertionError(f"unexpected execute query: {query!r}")
        if "status='pending'" in q:
            scope, key = args
            self.rows[(scope, key)]["status"] = "pending"
            self.rows[(scope, key)]["error"] = None
        elif "status='failed'" in q:
            scope, key, error = args
            self.rows[(scope, key)]["status"] = "failed"
            self.rows[(scope, key)]["error"] = error
        elif "status='completed'" in q:
            scope, key, result_json = args
            self.rows[(scope, key)]["status"] = "completed"
            self.rows[(scope, key)]["result"] = json.loads(result_json) if result_json else None
            self.rows[(scope, key)]["error"] = None
        else:
            raise AssertionError(f"unrecognized UPDATE: {query!r}")
        return "UPDATE 1"


class TestIdempotentContextManager(unittest.IsolatedAsyncioTestCase):
    async def test_first_call_creates_and_commits(self):
        pool = FakeIdempotencyPool()
        calls = []
        async with idempotent("test_scope_1", "key-a", pool=pool) as guard:
            self.assertFalse(guard.is_replay)
            calls.append(1)
            guard.result = {"ok": True}
        self.assertEqual(calls, [1])  # work actually ran
        self.assertEqual(pool.rows[("test_scope_1", "key-a")]["status"], "completed")
        self.assertEqual(pool.rows[("test_scope_1", "key-a")]["result"], {"ok": True})

    async def test_second_call_with_same_key_replays_without_rerunning(self):
        pool = FakeIdempotencyPool()
        calls = []

        async def do_work():
            calls.append(1)
            return {"value": 42}

        async with idempotent("test_scope_2", "key-b", pool=pool) as guard:
            self.assertFalse(guard.is_replay)
            guard.result = await do_work()

        async with idempotent("test_scope_2", "key-b", pool=pool) as guard2:
            self.assertTrue(guard2.is_replay)
            self.assertEqual(guard2.cached_result, {"value": 42})
            # The caller's contract: on replay, skip doing the work again.
            if not guard2.is_replay:
                await do_work()

        self.assertEqual(calls, [1])  # do_work() ran exactly once

    async def test_raising_marks_failed_and_third_call_is_fresh_retry(self):
        """Regression test for the exact bug being fixed in
        integrations/webhooks.py: a failed attempt must not become a
        permanent stuck duplicate — a later call with the same key must
        be treated as a legitimate retry, not silently swallowed."""
        pool = FakeIdempotencyPool()

        with self.assertRaises(RuntimeError):
            async with idempotent("test_scope_3", "key-c", pool=pool) as guard:
                self.assertFalse(guard.is_replay)
                raise RuntimeError("boom")

        self.assertEqual(pool.rows[("test_scope_3", "key-c")]["status"], "failed")

        # Third call (second attempt after the failure) must NOT be
        # treated as a duplicate/replay — it's a fresh retry opportunity.
        ran = []
        async with idempotent("test_scope_3", "key-c", pool=pool) as guard2:
            self.assertFalse(guard2.is_replay)
            ran.append(1)
            guard2.result = {"recovered": True}

        self.assertEqual(ran, [1])
        self.assertEqual(pool.rows[("test_scope_3", "key-c")]["status"], "completed")

    async def test_different_keys_never_collide(self):
        pool = FakeIdempotencyPool()
        async with idempotent("test_scope_4", "key-x", pool=pool) as g1:
            g1.result = "x"
        async with idempotent("test_scope_4", "key-y", pool=pool) as g2:
            self.assertFalse(g2.is_replay)  # different key -> not a replay
            g2.result = "y"

    async def test_different_scopes_with_same_key_never_collide(self):
        pool = FakeIdempotencyPool()
        async with idempotent("scope_a", "shared-key", pool=pool) as g1:
            g1.result = "a"
        async with idempotent("scope_b", "shared-key", pool=pool) as g2:
            self.assertFalse(g2.is_replay)  # different scope -> not a replay
            g2.result = "b"

    async def test_fresh_pending_raises_in_progress_not_a_silent_retry(self):
        """The actual concurrency bug this staleness check fixes: two
        genuinely-simultaneous callers for the same (scope, key) must NOT
        both run the guarded work — that would silently defeat the
        "exclusive execution" this module exists to provide (e.g. a user
        double-clicking the same button). A fresh 'pending' row (the
        first call hasn't finished yet) must raise IdempotencyInProgress
        instead of being treated like a dead/failed attempt."""
        pool = FakeIdempotencyPool()

        # First caller claims the key and is still "running" (never exits
        # the with-block in this test — simulates it being mid-flight).
        cm1 = idempotent("test_scope_5", "key-concurrent", pool=pool)
        guard1 = await cm1.__aenter__()
        self.assertFalse(guard1.is_replay)

        # Second caller arrives while the first is still in flight.
        with self.assertRaises(IdempotencyInProgress):
            async with idempotent("test_scope_5", "key-concurrent", pool=pool):
                pass  # must never get here

        # First caller finishes normally.
        guard1.result = {"done": True}
        await cm1.__aexit__(None, None, None)
        self.assertEqual(pool.rows[("test_scope_5", "key-concurrent")]["status"], "completed")

    async def test_stale_pending_is_treated_as_abandoned_and_retried(self):
        """The crash-recovery case: a 'pending' row old enough that the
        original attempt is assumed dead must NOT block a retry forever."""
        pool = FakeIdempotencyPool()

        cm1 = idempotent("test_scope_6", "key-crashed", pool=pool)
        await cm1.__aenter__()
        # Simulate the process that opened this guard having crashed
        # before ever exiting the with-block (so neither the 'completed'
        # nor 'failed' UPDATE ever ran) — the row is left at 'pending'.
        pool.mark_stale("test_scope_6", "key-crashed")

        ran = []
        async with idempotent("test_scope_6", "key-crashed", pool=pool) as guard2:
            self.assertFalse(guard2.is_replay)
            ran.append(1)
            guard2.result = {"recovered": True}

        self.assertEqual(ran, [1])
        self.assertEqual(pool.rows[("test_scope_6", "key-crashed")]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
