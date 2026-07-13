"""
Background Job Queue — Layer 3 enhancement.

Jobs are persisted via the cache adapter (Redis-backed in prod, in-process in dev).
Long-running operations (agent runs, code generation, deployments) submit a job
and return a job ID immediately. Clients poll GET /jobs/{id} or subscribe to
WebSocket channel `job:{id}` for live progress events.

Lifecycle:
    pending → running → completed | failed | cancelled

Usage:
    queue = get_job_queue()
    job_id = await queue.submit("generate_code", payload={"prompt": "..."}, ttl=3600)
    await queue.run(job_id, my_async_fn)    # runs fn, updates status automatically
    job = await queue.get(job_id)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

_JOB_TTL = 3600          # default 1 hour retention
_MAX_LOG  = 100          # max log lines stored per job


class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id          : str
    kind        : str
    payload     : dict
    status      : JobStatus        = JobStatus.PENDING
    result      : Optional[Any]    = None
    error       : Optional[str]    = None
    progress    : int              = 0          # 0–100
    log_lines   : list[str]        = field(default_factory=list)
    created_at  : float            = field(default_factory=time.time)
    started_at  : Optional[float]  = None
    finished_at : Optional[float]  = None
    ttl         : int              = _JOB_TTL

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"]      = self.status.value
        d["duration_ms"] = (
            round((self.finished_at - self.started_at) * 1000, 1)
            if self.started_at and self.finished_at else None
        )
        return d

    def append_log(self, line: str) -> None:
        if len(self.log_lines) < _MAX_LOG:
            self.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {line}")


# ── In-memory fallback store ──────────────────────────────────────────────────

class _MemStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def load(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    async def list_all(self) -> list[Job]:
        return list(self._jobs.values())

    async def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


# ── Redis-backed store ────────────────────────────────────────────────────────

class _RedisStore:
    """Serialises Job to JSON in Redis hash. Survives server restarts."""

    PREFIX = "job:"

    def __init__(self, cache) -> None:
        self._cache = cache

    async def save(self, job: Job) -> None:
        import json
        d = job.to_dict()
        d["log_lines"] = json.dumps(d["log_lines"])
        d["payload"]   = json.dumps(d["payload"])
        d["result"]    = json.dumps(d.get("result"))
        await self._cache.hset(f"{self.PREFIX}{job.id}", d)
        await self._cache._b.expire(
            self._cache._k(f"{self.PREFIX}{job.id}"), job.ttl
        )

    async def load(self, job_id: str) -> Optional[Job]:
        import json
        raw = await self._cache.hgetall(f"{self.PREFIX}{job_id}")
        if not raw:
            return None
        return Job(
            id         = raw["id"],
            kind       = raw["kind"],
            payload    = json.loads(raw.get("payload", "{}")),
            status     = JobStatus(raw.get("status", "pending")),
            result     = json.loads(raw.get("result", "null")),
            error      = raw.get("error") or None,
            progress   = int(raw.get("progress", 0)),
            log_lines  = json.loads(raw.get("log_lines", "[]")),
            created_at = float(raw.get("created_at", time.time())),
            started_at = float(raw["started_at"]) if raw.get("started_at") else None,
            finished_at= float(raw["finished_at"]) if raw.get("finished_at") else None,
            ttl        = int(raw.get("ttl", _JOB_TTL)),
        )

    async def list_all(self) -> list[Job]:
        # Without SCAN this is not efficient — for production use a sorted set index
        keys = await self._cache._b.keys(
            self._cache._k(f"{self.PREFIX}*")
        )
        jobs: list[Job] = []
        for key in keys:
            raw_key = key.decode() if isinstance(key, bytes) else key
            job_id  = raw_key.split(":")[-1]
            j = await self.load(job_id)
            if j:
                jobs.append(j)
        return jobs

    async def delete(self, job_id: str) -> None:
        await self._cache.delete(f"{self.PREFIX}{job_id}")


# ── Queue ─────────────────────────────────────────────────────────────────────

class JobQueue:
    """
    Submit async callables as background jobs.
    Workers run in the same asyncio event loop — no separate process needed.
    """

    def __init__(self, cache=None) -> None:
        self._store  = _RedisStore(cache) if cache else _MemStore()
        self._active : dict[str, asyncio.Task] = {}

    # ── Submission ─────────────────────────────────────────────────────────────

    async def submit(
        self,
        kind    : str,
        payload : dict | None = None,
        ttl     : int  = _JOB_TTL,
    ) -> str:
        job = Job(id=str(uuid.uuid4()), kind=kind, payload=payload or {}, ttl=ttl)
        await self._store.save(job)
        log.debug("job[%s] submitted kind=%s", job.id[:8], kind)
        return job.id

    # ── Execution ──────────────────────────────────────────────────────────────

    async def run(
        self,
        job_id  : str,
        fn      : Callable[..., Awaitable[Any]],
        *,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> Job:
        """
        Execute `fn(job)` in the background.
        `fn` receives the Job object and may update job.progress + job.append_log().
        Returns the Job after completion.
        """
        job = await self._store.load(job_id)
        if not job:
            raise KeyError(f"Job {job_id!r} not found")

        job.status     = JobStatus.RUNNING
        job.started_at = time.time()
        await self._store.save(job)

        async def _run():
            tracer = get_tracer()
            with tracer.start_span("job.run", service="job_queue") as span:
                for key, val in current_tags().items():
                    span.set_tag(key, val)
                span.set_tag("job_id", job_id)
                span.set_tag("kind", job.kind)
                try:
                    result      = await fn(job)
                    job.result  = result
                    job.status  = JobStatus.COMPLETED
                    job.progress = 100
                    job.append_log("Completed successfully")
                except asyncio.CancelledError:
                    job.status = JobStatus.CANCELLED
                    job.append_log("Cancelled")
                except Exception as exc:
                    job.status = JobStatus.FAILED
                    job.error  = str(exc)
                    job.append_log(f"Error: {exc}")
                    span.set_tag("error", str(exc))
                    log.warning("job[%s] failed: %s", job_id[:8], exc)
                finally:
                    job.finished_at = time.time()
                    self._active.pop(job_id, None)
                    await self._store.save(job)

        task = asyncio.create_task(_run())
        self._active[job_id] = task
        return job

    def run_background(
        self,
        job_id  : str,
        fn      : Callable[..., Awaitable[Any]],
    ) -> None:
        """Fire-and-forget: run job without awaiting completion."""
        asyncio.create_task(self.run(job_id, fn))

    # ── Queries ────────────────────────────────────────────────────────────────

    async def get(self, job_id: str) -> Optional[Job]:
        return await self._store.load(job_id)

    async def list_jobs(
        self,
        status  : Optional[JobStatus] = None,
        kind    : Optional[str]       = None,
        limit   : int                 = 50,
    ) -> list[Job]:
        jobs = await self._store.list_all()
        if status:
            jobs = [j for j in jobs if j.status == status]
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def cancel(self, job_id: str) -> bool:
        task = self._active.get(job_id)
        if task:
            task.cancel()
            return True
        job = await self.get(job_id)
        if job and job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            await self._store.save(job)
            return True
        return False

    # ── Stats ──────────────────────────────────────────────────────────────────

    async def stats(self) -> dict:
        all_jobs = await self._store.list_all()
        counts   = {s.value: 0 for s in JobStatus}
        for j in all_jobs:
            counts[j.status.value] += 1
        return {
            "total"  : len(all_jobs),
            "active" : len(self._active),
            "counts" : counts,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue: Optional[JobQueue] = None


def get_job_queue(cache=None) -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue(cache=cache)
    return _queue
