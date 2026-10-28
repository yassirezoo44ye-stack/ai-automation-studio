"""
JobQueue dispatch through the cache backends production actually uses.

Regression: with REDIS_URL unset (the production setup), the queue stored
jobs as hashes in LocalCacheBackend, whose keys() never listed hashes — the
scheduler saw no jobs, so every submitted automation / lead follow-up run
stayed 'pending' forever. With real Redis, hset() rejected the job's None /
bool fields, so submit() itself failed.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.cache.redis_adapter import LocalCacheBackend, RedisAdapter
from app.core.jobs.queue import JobQueue, JobStatus, _MemStore, _RedisStore


class StrictRedisBackend(LocalCacheBackend):
    """LocalCacheBackend that enforces redis-py's hset value rules
    (str/bytes/int/float only — None and bool raise DataError)."""

    async def hset(self, name: str, mapping: dict) -> None:
        for key, value in mapping.items():
            if value is None or isinstance(value, bool) or not isinstance(value, (str, bytes, int, float)):
                raise TypeError(f"Invalid input of type {type(value).__name__!r} for field {key!r}")
        await super().hset(name, mapping)

    @property
    def backend_name(self) -> str:
        return "redis"


async def _wait_for(event: asyncio.Event, timeout: float = 5.0) -> None:
    await asyncio.wait_for(event.wait(), timeout)


class TestJobQueueDispatch(unittest.IsolatedAsyncioTestCase):
    async def _assert_dispatches(self, q: JobQueue) -> None:
        seen: list[dict] = []
        done = asyncio.Event()

        async def handler(job):
            seen.append(job.payload)
            done.set()

        q.register_handler("automation.trigger.manual", handler)
        try:
            job_id = await q.submit(
                "automation.trigger.manual",
                payload={"run_id": "r-1"},
                org_id="org-1",
            )
            await _wait_for(done)
            self.assertEqual(seen, [{"run_id": "r-1", "organization_id": "org-1"}])
            for _ in range(50):
                job = await q.get(job_id)
                if job.status == JobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual(job.status, JobStatus.COMPLETED)
            self.assertFalse(job.dead)
            self.assertIsNone(job.error)
        finally:
            q._scheduler_task.cancel()

    async def test_local_cache_backend_dispatches_submitted_job(self):
        """REDIS_URL unset in production → in-process cache: jobs must run."""
        q = JobQueue(cache=RedisAdapter(LocalCacheBackend()))
        self.assertIsInstance(q._store, _MemStore)
        await self._assert_dispatches(q)

    async def test_redis_backend_stores_and_dispatches_job(self):
        q = JobQueue(cache=RedisAdapter(StrictRedisBackend()))
        self.assertIsInstance(q._store, _RedisStore)
        await self._assert_dispatches(q)

    async def test_redis_store_round_trips_unset_fields(self):
        store = _RedisStore(RedisAdapter(StrictRedisBackend()))
        q = JobQueue()
        q._store = store
        job_id = await q.submit("bench", payload={"a": 1})
        job = await store.load(job_id)
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertIsNone(job.started_at)
        self.assertIsNone(job.finished_at)
        self.assertIsNone(job.run_at)
        self.assertIsNone(job.error)
        self.assertFalse(job.dead)
        self.assertEqual(job.payload, {"a": 1})
        self.assertEqual([j.id for j in await store.list_all()], [job_id])

        job.dead = True
        await store.save(job)
        self.assertTrue((await store.load(job_id)).dead)


class TestLocalCacheBackendKeys(unittest.IsolatedAsyncioTestCase):
    async def test_keys_include_hashes(self):
        backend = LocalCacheBackend()
        await backend.set("axon:plain", "1")
        await backend.hset("axon:job:abc", {"id": "abc"})
        await backend.hset("other:job:xyz", {"id": "xyz"})
        self.assertEqual(sorted(await backend.keys("axon:*")), ["axon:job:abc", "axon:plain"])
        self.assertEqual(await backend.keys("axon:job:*"), ["axon:job:abc"])


if __name__ == "__main__":
    unittest.main()
