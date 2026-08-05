"""
JobQueue.submit()'s idempotency_key support — regression tests. Uses the
in-memory _MemStore (no cache/Redis needed) and patches app.core.db.get_pool
+ app.core.idempotency.idempotent so no live Postgres is required.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.jobs.queue import JobQueue


class FakeGuard:
    def __init__(self, is_replay: bool, cached_result=None):
        self.is_replay     = is_replay
        self.cached_result = cached_result
        self.result        = None


def _fake_idempotent_factory(store: dict):
    """Mimics app.core.idempotency.idempotent()'s real contract closely
    enough for these tests: first call for a (scope,key) is not a replay
    and persists whatever guard.result ends up being; subsequent calls
    with the same (scope,key) replay that stored result."""

    @asynccontextmanager
    async def _fake_idempotent(scope, key, *, pool, ttl_s=86400):
        cache_key = (scope, key)
        if cache_key in store:
            yield FakeGuard(is_replay=True, cached_result=store[cache_key])
            return
        guard = FakeGuard(is_replay=False)
        yield guard
        store[cache_key] = guard.result

    return _fake_idempotent


class TestJobQueueIdempotencyKey(unittest.IsolatedAsyncioTestCase):
    async def test_no_idempotency_key_behaves_exactly_as_before(self):
        q = JobQueue()
        jid1 = await q.submit("bench")
        jid2 = await q.submit("bench")
        self.assertNotEqual(jid1, jid2)  # unrelated calls still create distinct jobs

    async def test_same_idempotency_key_returns_same_job_id(self):
        q = JobQueue()
        store: dict = {}
        with unittest.mock.patch("app.core.db.get_pool", return_value=object()), \
             unittest.mock.patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            jid1 = await q.submit("send_email", idempotency_key="req-123")
            jid2 = await q.submit("send_email", idempotency_key="req-123")
        self.assertEqual(jid1, jid2)
        all_jobs = await q._store.list_all()
        self.assertEqual(len(all_jobs), 1)  # only one job actually created

    async def test_different_idempotency_keys_create_different_jobs(self):
        q = JobQueue()
        store: dict = {}
        with unittest.mock.patch("app.core.db.get_pool", return_value=object()), \
             unittest.mock.patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            jid1 = await q.submit("send_email", idempotency_key="req-a")
            jid2 = await q.submit("send_email", idempotency_key="req-b")
        self.assertNotEqual(jid1, jid2)

    async def test_different_kind_same_key_does_not_collide(self):
        """The dedup scope key includes `kind`, so two different job kinds
        submitted with the same caller-chosen idempotency_key must not be
        treated as the same logical request."""
        q = JobQueue()
        store: dict = {}
        with unittest.mock.patch("app.core.db.get_pool", return_value=object()), \
             unittest.mock.patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            jid1 = await q.submit("send_email", idempotency_key="same-key")
            jid2 = await q.submit("send_sms", idempotency_key="same-key")
        self.assertNotEqual(jid1, jid2)

    async def test_dedup_check_failure_fails_open(self):
        """If the idempotency mechanism itself errors (pool unavailable,
        Redis/Postgres down), submission must still succeed rather than
        blocking the caller — this is waste-prevention, not
        financial-correctness."""
        q = JobQueue()
        with unittest.mock.patch(
            "app.core.db.get_pool", side_effect=RuntimeError("no pool configured"),
        ):
            job_id = await q.submit("send_email", idempotency_key="req-999")
        self.assertIsNotNone(job_id)
        job = await q.get(job_id)
        self.assertIsNotNone(job)


if __name__ == "__main__":
    unittest.main()
