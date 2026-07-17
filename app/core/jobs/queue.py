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
import os
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

# Priority dispatch order for the scheduler (lower sorts first). FIFO within
# a class — high-priority jobs can't starve low ones forever because the
# worker semaphore admits jobs as slots free up, and each tick re-sorts.
_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}
_RETRY_BASE_S   = 0.5     # exponential backoff base for retries
_RETRY_CAP_S    = 60.0    # backoff ceiling


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
    priority    : str              = "normal"   # high | normal | low
    max_retries : int              = 0
    attempts    : int              = 0
    run_at      : Optional[float]  = None       # epoch; None = immediately
    dead        : bool             = False      # failed beyond max_retries (DLQ)

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
            priority   = raw.get("priority") or "normal",
            max_retries= int(raw.get("max_retries", 0) or 0),
            attempts   = int(raw.get("attempts", 0) or 0),
            run_at     = float(raw["run_at"]) if raw.get("run_at") else None,
            dead       = str(raw.get("dead", "")).lower() in ("true", "1"),
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
        # kind → handler; jobs of a registered kind are dispatched by the
        # scheduler loop (delayed jobs, requeued DLQ jobs) without the
        # caller having to hold the coroutine.
        self._handlers   : dict[str, Callable[[Job], Awaitable[Any]]] = {}
        self._dispatching: set[str] = set()
        self._scheduler_task: Optional[asyncio.Task] = None
        # Worker pool: bounds how many scheduler-dispatched jobs run at
        # once so a burst can't starve the event loop.
        self._worker_sem = asyncio.Semaphore(int(os.getenv("JOB_WORKERS", "10")))

    # ── Submission ─────────────────────────────────────────────────────────────

    async def submit(
        self,
        kind    : str,
        payload : dict | None = None,
        ttl     : int  = _JOB_TTL,
        *,
        priority    : str = "normal",
        max_retries : int = 0,
        run_at      : Optional[float] = None,
    ) -> str:
        if priority not in _PRIORITY_ORDER:
            priority = "normal"
        job = Job(
            id=str(uuid.uuid4()), kind=kind, payload=payload or {}, ttl=ttl,
            priority=priority, max_retries=max_retries, run_at=run_at,
        )
        await self._store.save(job)
        log.debug("job[%s] submitted kind=%s priority=%s", job.id[:8], kind, priority)
        return job.id

    # ── Handler registry + scheduler (delayed jobs, DLQ requeue) ──────────────

    def register_handler(self, kind: str, fn: Callable[[Job], Awaitable[Any]]) -> None:
        """Jobs of this kind (including ones submitted with run_at in the
        future, and DLQ jobs put back via requeue()) are picked up and run
        by the scheduler automatically."""
        self._handlers[kind] = fn
        self._ensure_scheduler()

    def _ensure_scheduler(self) -> None:
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self._dispatch_due()
            except Exception:
                log.exception("job scheduler tick failed")
            await asyncio.sleep(1.0)

    async def _dispatch_due(self) -> None:
        now  = time.time()
        jobs = await self._store.list_all()
        due = [
            j for j in jobs
            if j.status == JobStatus.PENDING
            and not j.dead
            and j.kind in self._handlers
            and (j.run_at is None or j.run_at <= now)
            and j.id not in self._active
            and j.id not in self._dispatching
        ]
        due.sort(key=lambda j: (_PRIORITY_ORDER.get(j.priority, 1), j.created_at))
        for j in due:
            self._dispatching.add(j.id)
            asyncio.create_task(self._run_pooled(j.id, self._handlers[j.kind]))

    async def _run_pooled(self, job_id: str, fn) -> None:
        try:
            async with self._worker_sem:
                job = await self._store.load(job_id)
                if job is None or job.status != JobStatus.PENDING:
                    return
                await self._execute(job, fn)
        finally:
            self._dispatching.discard(job_id)

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

        # Mark RUNNING before returning — callers have always been able to
        # observe the transition immediately after run().
        job.status     = JobStatus.RUNNING
        job.started_at = time.time()
        await self._store.save(job)

        task = asyncio.create_task(self._execute(job, fn))
        self._active[job_id] = task
        return job

    async def _execute(self, job: Job, fn: Callable[..., Awaitable[Any]]) -> None:
        """Run the job to a terminal state, retrying with exponential
        backoff up to job.max_retries; beyond that the job is marked dead
        (dead-letter) so it can be inspected and requeued explicitly."""
        job_id = job.id
        if job.status != JobStatus.RUNNING:   # scheduler path — run() already set it
            job.status     = JobStatus.RUNNING
            job.started_at = time.time()
            await self._store.save(job)

        tracer = get_tracer()
        with tracer.start_span("job.run", service="job_queue") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("job_id", job_id)
            span.set_tag("kind", job.kind)
            try:
                while True:
                    try:
                        result      = await fn(job)
                        job.result  = result
                        job.status  = JobStatus.COMPLETED
                        job.progress = 100
                        job.append_log("Completed successfully")
                        return
                    except asyncio.CancelledError:
                        job.status = JobStatus.CANCELLED
                        job.append_log("Cancelled")
                        return
                    except Exception as exc:
                        job.attempts += 1
                        job.error = str(exc)
                        if job.attempts <= job.max_retries:
                            backoff = min(_RETRY_BASE_S * (2 ** job.attempts), _RETRY_CAP_S)
                            job.append_log(
                                f"Attempt {job.attempts}/{job.max_retries + 1} failed: {exc} "
                                f"— retrying in {backoff:.1f}s"
                            )
                            await self._store.save(job)
                            await asyncio.sleep(backoff)
                            continue
                        job.status = JobStatus.FAILED
                        job.dead   = True   # final failure → dead-letter list
                        job.append_log(f"Error: {exc}")
                        span.set_tag("error", str(exc))
                        log.warning("job[%s] failed (attempt %d): %s",
                                    job_id[:8], job.attempts, exc)
                        return
            finally:
                job.finished_at = time.time()
                self._active.pop(job_id, None)
                await self._store.save(job)

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

    async def dead_letter(self, limit: int = 50) -> list[Job]:
        """Jobs that failed beyond their retry budget — inspect + requeue."""
        jobs = [j for j in await self._store.list_all() if j.dead]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def requeue(self, job_id: str) -> bool:
        """Put a dead-lettered job back in PENDING with a fresh retry
        budget. If its kind has a registered handler, the scheduler picks
        it up; otherwise the caller re-runs it via run()."""
        job = await self._store.load(job_id)
        if job is None or not job.dead:
            return False
        job.dead        = False
        job.status      = JobStatus.PENDING
        job.attempts    = 0
        job.error       = None
        job.run_at      = None
        job.finished_at = None
        job.append_log("Requeued from dead-letter")
        await self._store.save(job)
        return True

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
            "dead"   : sum(1 for j in all_jobs if j.dead),
            "counts" : counts,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue: Optional[JobQueue] = None


def get_job_queue(cache=None) -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue(cache=cache)
    return _queue
