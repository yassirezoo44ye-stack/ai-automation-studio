"""
Automation Scheduler — Phase 5 Gate 3.

Responsibilities:
  1. Job handlers for "automation.trigger.schedule", "automation.trigger.webhook",
     and "automation.trigger.manual" — registered at startup via factory.py.
  2. Background scheduler task that discovers active schedule triggers and
     enqueues timed runs (polling loop; period configurable via env).
  3. Idempotency keys prevent double-scheduling within the same cron tick.

Design rules:
  • Does NOT import or modify app/core/workflow/engine.py.
  • Does NOT create a second queue or a second workflow engine.
  • Workers receive a job dict; they persist a pending run (already done by
    the API/webhook endpoints) then hand off to the WorkflowEngine.
  • The engine is in-memory; if a run_id is already in the engine's _active
    dict (e.g. duplicate delivery), the engine's own idempotency handles it.
  • Scheduler period: AUTOMATION_SCHEDULER_INTERVAL_S (default 60 s).
  • Minimum cron granularity: 1 minute (cron ticks are floored to the minute).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Scheduler config ──────────────────────────────────────────────────────────
_SCHEDULER_INTERVAL = int(os.getenv("AUTOMATION_SCHEDULER_INTERVAL_S", "60"))

# ── Background task handle (set by start/stop) ────────────────────────────────
_scheduler_task: Optional[asyncio.Task] = None


# =============================================================================
# Job handlers
# =============================================================================

async def _handle_automation_run(job: Any) -> None:
    """
    Common handler for manual, webhook, and schedule-triggered automation runs.

    The job payload MUST contain:
      organization_id  — server-verified tenant id
      run_id           — UUID string already persisted as 'pending' in DB
      definition_id    — optional; used to load the workflow definition

    This handler:
      1. Loads the workflow definition from the DB.
      2. Builds a WorkflowEngine run from the definition dict.
      3. Executes it (best-effort).
      4. Persistence is handled by the persistence adapter which is expected
         to be called from the engine's hooks — for v1 we update the run
         status directly here after completion.
    """
    from app.core.db import get_pool

    payload: dict = getattr(job, "payload", {}) if not isinstance(job, dict) else job
    org_id     = payload.get("organization_id")
    run_id     = payload.get("run_id")
    def_id     = payload.get("definition_id")

    if not org_id or not run_id:
        log.error("automation handler: missing org_id or run_id in payload")
        return

    log.info("automation run starting: run_id=%s org=%s", run_id, org_id[:8])

    # Mark run as 'running' in DB
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE automation_runs SET status='running', started_at=now() WHERE run_id=$1",
                run_id,
            )
    except Exception:
        log.warning("automation: could not mark run as running run_id=%s", run_id, exc_info=True)

    # Execute the workflow (if definition is available)
    error: Optional[str] = None
    final_status = "completed"

    try:
        if def_id:
            await _execute_definition(org_id, run_id, def_id, payload.get("context", {}))
        else:
            # Bare run without a saved definition — no steps to execute.
            log.info("automation: bare run (no definition) run_id=%s", run_id)
    except Exception as exc:
        log.exception("automation run failed run_id=%s", run_id)
        error = str(exc)[:1000]
        final_status = "failed"

    # Mark final status in DB
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE automation_runs
                SET status=$2, error=$3, finished_at=now()
                WHERE run_id=$1
                """,
                run_id, final_status, error,
            )
    except Exception:
        log.warning("automation: could not mark run finished run_id=%s", run_id, exc_info=True)

    log.info("automation run finished: run_id=%s status=%s", run_id, final_status)


async def _execute_definition(
    org_id: str,
    run_id: str,
    definition_id: str,
    context: dict,
) -> None:
    """
    Load a workflow definition from DB and execute it via WorkflowEngine.

    The definition JSONB column is expected to contain the engine's step
    specification.  In v1 we support a simple sequential list format:
      {"steps": [{"id": "...", "name": "...", "kind": "noop", ...}, ...]}

    An engine.WorkflowEngine.execute() call is made with a minimal step set.
    Full step-kind dispatch (API call, script, sub-agent, etc.) is a v2 concern.
    """
    from app.core.db import get_pool
    from app.core.workflow.engine import WorkflowRun, WorkflowStep, get_workflow_engine

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT definition FROM automation_definitions WHERE id=$1 AND organization_id=$2",
            uuid.UUID(definition_id), uuid.UUID(org_id),
        )
    if row is None:
        raise ValueError(f"Definition {definition_id} not found for org {org_id[:8]}")

    defn: dict = row["definition"] if isinstance(row["definition"], dict) else {}
    steps_spec: list = defn.get("steps", [])

    engine = get_workflow_engine()

    # Build WorkflowStep objects for each step spec
    steps_dict: dict[str, WorkflowStep] = {}
    for spec in steps_spec:
        if not isinstance(spec, dict) or not spec.get("id"):
            continue
        step_id = spec["id"]
        kind    = spec.get("kind", "noop")
        step    = WorkflowStep(
            id               = step_id,
            name             = spec.get("name", step_id),
            fn               = _make_step_fn(kind, spec),
            args             = spec.get("args", {}),
            depends_on       = spec.get("depends_on", []),
            requires_approval= bool(spec.get("requires_approval", False)),
        )
        steps_dict[step_id] = step

    run = WorkflowRun(
        run_id  = run_id,
        name    = defn.get("name", run_id),
        steps   = steps_dict,
        context = {**context, "definition_id": definition_id, "org_id": org_id},
    )

    await engine.execute(run)


def _make_step_fn(kind: str, spec: dict):
    """Return a coroutine function for a step kind."""
    async def _noop(**kwargs):
        log.debug("automation step noop kind=%s id=%s", kind, spec.get("id"))
        return {"kind": kind, "status": "noop"}

    return _noop


# Register the SAME handler for all three trigger kinds
handle_manual_trigger  = _handle_automation_run
handle_webhook_trigger = _handle_automation_run
handle_schedule_trigger = _handle_automation_run


# =============================================================================
# Schedule-trigger polling loop
# =============================================================================

def _floor_minute(ts: float) -> int:
    """Floor a unix timestamp to the minute boundary."""
    return int(ts) - (int(ts) % 60)


async def _tick_schedule_triggers() -> None:
    """
    One scheduler tick: find all active schedule triggers and enqueue
    any that are due for the current minute.

    Trigger format inside triggers JSONB:
      {"id": "...", "kind": "schedule", "cron": "*/5 * * * *", "next_run_at": <epoch>}

    For v1 we use a simple `next_run_at` field rather than a full cron parser.
    If `next_run_at` <= now and the definition is active, we submit a job.
    Idempotency key: "auto-sched:{definition_id}:{cron_tick_epoch}"
    """
    from app.core.db import get_pool

    now = time.time()
    tick_epoch = _floor_minute(now)

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, organization_id, triggers
                FROM automation_definitions
                WHERE is_active = true AND deleted_at IS NULL
                  AND triggers != '[]'::jsonb
                """
            )
    except Exception:
        log.warning("automation scheduler: DB query failed", exc_info=True)
        return

    from app.core.jobs import get_job_queue
    queue = get_job_queue()

    for row in rows:
        def_id  = str(row["id"])
        org_id  = str(row["organization_id"])
        triggers = row["triggers"]
        if not isinstance(triggers, list):
            continue

        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            if trigger.get("kind") != "schedule":
                continue
            trigger_id = trigger.get("id")
            next_run   = trigger.get("next_run_at")
            if not trigger_id or next_run is None:
                continue

            try:
                next_run_ts = float(next_run)
            except (TypeError, ValueError):
                continue

            if next_run_ts > now:
                continue  # not due yet

            idempotency_key = f"auto-sched:{def_id}:{tick_epoch}"
            run_id = str(uuid.uuid4())

            try:
                # Insert pending run first
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO automation_runs
                            (organization_id, definition_id, run_id, name, status,
                             context, triggered_by)
                        VALUES ($1, $2, $3, 'schedule-run', 'pending', '{}', 'schedule')
                        ON CONFLICT DO NOTHING
                        """,
                        uuid.UUID(org_id),
                        uuid.UUID(def_id),
                        run_id,
                    )

                payload = {
                    "organization_id": org_id,
                    "run_id": run_id,
                    "definition_id": def_id,
                    "trigger_id": trigger_id,
                    "context": {},
                    "triggered_by": "schedule",
                }
                await queue.submit(
                    "automation.trigger.schedule",
                    payload=payload,
                    org_id=org_id,
                    idempotency_key=idempotency_key,
                )
                log.info(
                    "automation scheduler: enqueued def=%s trigger=%s run=%s",
                    def_id[:8], trigger_id, run_id,
                )
            except Exception:
                log.warning(
                    "automation scheduler: failed to enqueue def=%s trigger=%s",
                    def_id[:8], trigger_id, exc_info=True,
                )


async def _scheduler_loop() -> None:
    """Background scheduler loop — runs until cancelled."""
    log.info("automation scheduler: started (interval=%ds)", _SCHEDULER_INTERVAL)
    while True:
        try:
            await _tick_schedule_triggers()
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("automation scheduler: unexpected error in tick")
        try:
            await asyncio.sleep(_SCHEDULER_INTERVAL)
        except asyncio.CancelledError:
            break
    log.info("automation scheduler: stopped")


# =============================================================================
# Lifecycle (called from factory.py)
# =============================================================================

def start_scheduler() -> None:
    """Start the background scheduler task.  Call once from factory lifespan."""
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        log.warning("automation scheduler: already running, skipping start")
        return
    _scheduler_task = asyncio.get_event_loop().create_task(
        _scheduler_loop(), name="automation-scheduler"
    )
    log.info("automation scheduler: task created")


async def stop_scheduler() -> None:
    """Stop the background scheduler task gracefully.  Call from lifespan teardown."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        return
    _scheduler_task.cancel()
    try:
        await asyncio.wait_for(_scheduler_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    _scheduler_task = None
    log.info("automation scheduler: shutdown complete")
