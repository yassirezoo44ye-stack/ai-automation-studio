"""
SyncEngine — schedules and runs provider sync() calls through the
EXISTING background job queue (app/core/jobs). Reuses that queue's
retry/priority/scheduled-run machinery rather than reimplementing a
second job runner — "Retry engine" and "Background job support" from
the spec are the same underlying primitive here, not two systems.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.integrations.types import SyncResult, SyncStatus

log = logging.getLogger(__name__)

_JOB_KIND = "integration_sync"
_MAX_RETRIES = 3


class SyncEngine:
    def __init__(self, pool) -> None:
        self._pool = pool
        self._handler_registered = False

    def _ensure_handler(self) -> None:
        if self._handler_registered:
            return
        self._handler_registered = True
        from app.core.jobs import get_job_queue
        get_job_queue().register_handler(_JOB_KIND, self._run_sync_job)

    def start(self) -> None:
        """Register the job-queue handler eagerly at boot, so a delayed or
        DLQ-requeued sync job is picked up immediately rather than waiting
        for the first schedule_sync() call in the process."""
        self._ensure_handler()

    async def schedule_sync(self, *, provider_id: str, organization_id: str, run_at: Optional[float] = None) -> str:
        """Enqueue a sync run. Returns the job id (also recorded in
        integration_sync_runs immediately as 'pending' so callers can
        list sync history without waiting on the job queue)."""
        self._ensure_handler()
        from app.core.jobs import get_job_queue

        run_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO integration_sync_runs (id, provider_id, organization_id, status, started_at)
                   VALUES ($1,$2,$3,'pending',NOW())""",
                uuid.UUID(run_id), provider_id, uuid.UUID(organization_id),
            )
        await get_job_queue().submit(
            _JOB_KIND, {"run_id": run_id, "provider_id": provider_id, "organization_id": organization_id},
            max_retries=_MAX_RETRIES, run_at=run_at,
        )
        return run_id

    async def _run_sync_job(self, job) -> dict:
        run_id = job.payload["run_id"]
        provider_id = job.payload["provider_id"]
        organization_id = job.payload["organization_id"]

        from app.integrations.registry import get_integration_registry
        from app.integrations.credential_store import get_credential_store
        from app.integrations.retry import get_integration_circuit_breaker

        breaker = get_integration_circuit_breaker()
        target = f"{provider_id}:{organization_id}"
        result: SyncResult
        try:
            provider = get_integration_registry().require(provider_id)
            credential = await get_credential_store(self._pool).load(provider_id, organization_id)
            if credential is None:
                result = SyncResult(status=SyncStatus.FAILED, message="not connected")
            else:
                result = await provider.sync(credential)
                breaker.record_success(target)
        except Exception as exc:
            breaker.record_failure(target)
            result = SyncResult(status=SyncStatus.FAILED, message=str(exc))
            log.warning("integration sync failed provider=%s org=%s: %s", provider_id, organization_id, exc)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE integration_sync_runs
                   SET status=$2, items_synced=$3, message=$4, cursor=$5, finished_at=NOW()
                   WHERE id=$1""",
                uuid.UUID(run_id), result.status.value, result.items_synced, result.message, result.cursor,
            )

        try:
            from app.integrations.events import publish_sync_completed, publish_sync_failed
            if result.status == SyncStatus.SUCCEEDED:
                await publish_sync_completed(provider_id, organization_id, items_synced=result.items_synced)
            else:
                await publish_sync_failed(provider_id, organization_id, message=result.message)
        except Exception:
            log.warning("integration event publish failed for sync run=%s", run_id, exc_info=True)

        return {"status": result.status.value, "items_synced": result.items_synced}

    async def list_history(self, *, provider_id: str, organization_id: str, limit: int = 20) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, status, items_synced, message, started_at, finished_at
                   FROM integration_sync_runs
                   WHERE provider_id=$1 AND organization_id=$2
                   ORDER BY started_at DESC LIMIT $3""",
                provider_id, uuid.UUID(organization_id), min(limit, 200),
            )
        return [dict(r) for r in rows]


_engine: Optional[SyncEngine] = None


def get_sync_engine(pool=None) -> SyncEngine:
    global _engine
    if _engine is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _engine = SyncEngine(pool)
    return _engine
