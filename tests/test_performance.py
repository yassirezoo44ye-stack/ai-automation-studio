"""
Deterministic performance tests for the reliability/perf primitives.

These verify the OVERHEAD of the infrastructure added in the Performance &
Reliability phase stays negligible — they are unit-level and mock-free, so
they hold on a loaded CI runner (generous ceilings, tight expectations).
The full end-to-end load test lives in scripts/load_test.py and is run
against a real server outside CI (a saturated shared runner cannot hold
wall-clock latency SLOs; see PERFORMANCE.md).
"""
import asyncio
import time

from app.core.jobs.queue import JobQueue, JobStatus
from app.core.reliability import Bulkhead, BulkheadFull, CircuitBreaker


class TestCircuitBreakerOverhead:
    def test_allow_is_microseconds(self):
        cb = CircuitBreaker()
        t0 = time.perf_counter()
        for _ in range(10_000):
            cb.allow("provider-x")
        elapsed = time.perf_counter() - t0
        # 10k decisions in well under 100ms → <10µs per call on the AI hot path
        assert elapsed < 0.5, f"10k allow() took {elapsed:.3f}s"

    def test_state_machine_transitions(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_s=0.05)
        assert cb.allow("p")
        cb.record_failure("p")
        cb.record_failure("p")
        assert not cb.allow("p")          # open
        time.sleep(0.06)
        assert cb.allow("p")              # half-open probe
        cb.record_success("p")
        assert cb.allow("p")              # closed again


class TestBulkhead:
    async def test_sheds_load_at_limit_without_queueing(self):
        bh = Bulkhead("test", limit=2)
        release = asyncio.Event()

        async def hold():
            async with bh.acquire():
                await release.wait()

        t1 = asyncio.create_task(hold())
        t2 = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        assert bh.in_flight == 2

        t0 = time.perf_counter()
        try:
            async with bh.acquire():
                raise AssertionError("third acquire should have been shed")
        except BulkheadFull:
            pass
        # Shedding must be immediate — no queueing behind the held slots.
        assert time.perf_counter() - t0 < 0.05

        release.set()
        await asyncio.gather(t1, t2)
        assert bh.in_flight == 0

    async def test_acquire_release_overhead(self):
        bh = Bulkhead("perf", limit=100)
        t0 = time.perf_counter()
        for _ in range(10_000):
            async with bh.acquire():
                pass
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"10k acquire/release took {elapsed:.3f}s"


class TestJobQueueScheduling:
    async def test_run_dispatch_under_budget(self):
        """Job dispatch overhead (submit → handler running) must stay well
        under the 50ms scheduling budget — measured as the time run() takes
        to hand off, excluding the work itself."""
        q = JobQueue()
        started = asyncio.Event()

        async def work(job):
            started.set()
            return "ok"

        jid = await q.submit("bench")
        t0 = time.perf_counter()
        await q.run(jid, work)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        dispatch_ms = (time.perf_counter() - t0) * 1000
        assert dispatch_ms < 50, f"dispatch took {dispatch_ms:.1f}ms (budget 50ms)"

    async def test_retry_then_dead_letter(self):
        q = JobQueue()
        attempts = {"n": 0}

        async def flaky(job):
            attempts["n"] += 1
            raise RuntimeError("boom")

        jid = await q.submit("flaky", max_retries=1)
        await q.run(jid, flaky)
        for _ in range(100):
            j = await q.get(jid)
            if j.status == JobStatus.FAILED:
                break
            await asyncio.sleep(0.05)
        j = await q.get(jid)
        assert j.status == JobStatus.FAILED and j.dead and attempts["n"] == 2
        assert [d.id for d in await q.dead_letter()] == [jid]
        assert await q.requeue(jid)
        assert (await q.get(jid)).status == JobStatus.PENDING

    async def test_priority_ordering_in_dispatch(self):
        q = JobQueue()
        order: list[str] = []

        async def rec(job):
            order.append(job.priority)

        q.register_handler("prio", rec)
        await q.submit("prio", priority="low")
        await q.submit("prio", priority="high")
        for _ in range(60):
            if len(order) >= 2:
                break
            await asyncio.sleep(0.1)
        assert order[0] == "high", order


class TestCacheHitPath:
    async def test_cached_hit_is_fast_and_computes_once(self):
        from app.core.cache import cached, invalidate

        calls = {"n": 0}

        async def compute():
            calls["n"] += 1
            await asyncio.sleep(0.05)  # simulated expensive load
            return {"v": calls["n"]}

        key = f"perf:test:{time.time()}"
        await cached(key, compute, ttl=60)      # miss — pays the 50ms
        t0 = time.perf_counter()
        hit = await cached(key, compute, ttl=60)
        hit_ms = (time.perf_counter() - t0) * 1000
        assert hit == {"v": 1} and calls["n"] == 1
        assert hit_ms < 25, f"cache hit took {hit_ms:.1f}ms"
        await invalidate(key)
