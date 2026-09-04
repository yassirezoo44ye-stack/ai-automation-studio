"""
Automation Persistence Adapter — Phase 5 Gate 3.

Side-channel persistence for Engine A (app/core/workflow/engine.py).

IMPORTANT: Engine A is NEVER modified. This module reads Engine A's
WorkflowRun / WorkflowStep dataclasses after the fact and writes their
state to the automation_runs / automation_run_steps / automation_approvals
tables. All methods are best-effort (errors are logged, never re-raised)
*except* record_approval_decision, whose DB write must succeed before the
Engine A registry is unblocked — the router handles that transaction contract.

Organization ID handling
────────────────────────
Engine A carries organization_id as a TEXT string in run.context.
DB columns are UUID. The adapter converts TEXT → UUID via uuid.UUID().
If the cast fails, the persistence write is skipped and a warning is logged —
the workflow run is *not* affected.

Timestamp handling
──────────────────
Engine A stores started_at/finished_at as Unix epoch floats (time.time()).
Converted to UTC-aware datetime via datetime.fromtimestamp(ts, tz=timezone.utc).
None → None (not converted).

JSON serialization
──────────────────
Non-serializable step.result / step.args values are coerced to strings and
stored with {"value": "<str>", "type": "string", "coerced": true} so the
adapter never crashes the workflow.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.core.db import get_pool
from app.core.workflow.engine import WorkflowRun, WorkflowStep

log = logging.getLogger(__name__)


# ── Serialization helpers ──────────────────────────────────────────────────────

def _safe_json(value: Any) -> str | None:
    """Serialize `value` to a JSON string safe for asyncpg JSONB binding.
    Returns None when value is None. Non-serializable values are wrapped in
    a coerced envelope so they never crash the caller."""
    if value is None:
        return None
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return json.dumps({"value": str(value), "type": "string", "coerced": True})


def _safe_context(ctx: dict) -> str:
    """Serialize run.context, replacing non-serializable entries."""
    safe: dict = {}
    for k, v in ctx.items():
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = {"value": str(v), "type": "string", "coerced": True}
    return json.dumps(safe)


def _epoch_to_dt(ts: float | None) -> datetime | None:
    """Convert a Unix epoch float to a UTC-aware datetime, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _parse_org_id(raw: Any) -> UUID | None:
    """Parse organization_id string to UUID. Returns None on failure."""
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError):
        log.warning("automation persistence: invalid organization_id %r — skipping write", raw)
        return None


# ── Adapter ────────────────────────────────────────────────────────────────────

class AutomationPersistence:
    """
    Side-channel persistence for Engine A workflow runs.

    All upsert_* / create_* methods are best-effort: they log exceptions but
    never propagate them to Engine A. Only record_approval_decision is
    transactional and expected to propagate failures (the router handles the
    caller-visible error path).
    """

    # ── Run ───────────────────────────────────────────────────────────────────

    async def upsert_run(
        self,
        run: WorkflowRun,
        *,
        definition_id: str | None = None,
        triggered_by: str | None = None,
        triggered_by_user: str | None = None,
    ) -> None:
        """Write or update automation_runs from a WorkflowRun. Best-effort."""
        org_id = _parse_org_id(run.context.get("organization_id"))
        if org_id is None:
            log.warning("upsert_run: missing/invalid org_id for run %s — skipping", run.run_id)
            return
        try:
            def_id: UUID | None = None
            if definition_id:
                try:
                    def_id = UUID(definition_id)
                except ValueError:
                    def_id = None
            tbu: UUID | None = None
            if triggered_by_user:
                try:
                    tbu = UUID(triggered_by_user)
                except ValueError:
                    tbu = None

            async with get_pool().acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO automation_runs
                        (organization_id, definition_id, run_id, name, status,
                         context, error, triggered_by, triggered_by_user,
                         created_at, started_at, finished_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (run_id) DO UPDATE SET
                        name         = EXCLUDED.name,
                        status       = EXCLUDED.status,
                        context      = EXCLUDED.context,
                        error        = EXCLUDED.error,
                        started_at   = EXCLUDED.started_at,
                        finished_at  = EXCLUDED.finished_at
                    """,
                    org_id,
                    def_id,
                    run.run_id,
                    run.name,
                    run.status.value,
                    _safe_context(run.context),
                    run.error,
                    triggered_by,
                    tbu,
                    _epoch_to_dt(run.created_at),
                    _epoch_to_dt(run.started_at),
                    _epoch_to_dt(run.finished_at),
                )
        except Exception:
            log.exception("upsert_run failed for run %s (non-fatal)", run.run_id)

    # ── Steps ─────────────────────────────────────────────────────────────────

    async def upsert_step(
        self,
        run_id: str,
        org_id: str,
        step: WorkflowStep,
    ) -> None:
        """Write or update one step in automation_run_steps. Best-effort."""
        org_uuid = _parse_org_id(org_id)
        if org_uuid is None:
            return
        try:
            async with get_pool().acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO automation_run_steps
                        (run_id, organization_id, step_id, name, status,
                         attempt, requires_approval, depends_on, args,
                         result, error, started_at, finished_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (run_id, step_id) DO UPDATE SET
                        name              = EXCLUDED.name,
                        status            = EXCLUDED.status,
                        attempt           = EXCLUDED.attempt,
                        requires_approval = EXCLUDED.requires_approval,
                        depends_on        = EXCLUDED.depends_on,
                        args              = EXCLUDED.args,
                        result            = EXCLUDED.result,
                        error             = EXCLUDED.error,
                        started_at        = EXCLUDED.started_at,
                        finished_at       = EXCLUDED.finished_at
                    """,
                    run_id,
                    org_uuid,
                    step.id,
                    step.name,
                    step.status.value,
                    step.attempt,
                    step.requires_approval,
                    json.dumps(step.depends_on),
                    _safe_json(step.args) or "{}",
                    _safe_json(step.result),
                    step.error,
                    _epoch_to_dt(step.started_at),
                    _epoch_to_dt(step.finished_at),
                )
        except Exception:
            log.exception(
                "upsert_step failed for run %s step %s (non-fatal)",
                run_id, step.id,
            )

    async def upsert_steps_bulk(
        self,
        run_id: str,
        org_id: str,
        steps: dict[str, WorkflowStep],
    ) -> None:
        """Bulk UPSERT all steps in one transaction. Best-effort."""
        org_uuid = _parse_org_id(org_id)
        if org_uuid is None:
            return
        try:
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    for step in steps.values():
                        await conn.execute(
                            """
                            INSERT INTO automation_run_steps
                                (run_id, organization_id, step_id, name, status,
                                 attempt, requires_approval, depends_on, args,
                                 result, error, started_at, finished_at)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                            ON CONFLICT (run_id, step_id) DO UPDATE SET
                                name              = EXCLUDED.name,
                                status            = EXCLUDED.status,
                                attempt           = EXCLUDED.attempt,
                                requires_approval = EXCLUDED.requires_approval,
                                depends_on        = EXCLUDED.depends_on,
                                args              = EXCLUDED.args,
                                result            = EXCLUDED.result,
                                error             = EXCLUDED.error,
                                started_at        = EXCLUDED.started_at,
                                finished_at       = EXCLUDED.finished_at
                            """,
                            run_id,
                            org_uuid,
                            step.id,
                            step.name,
                            step.status.value,
                            step.attempt,
                            step.requires_approval,
                            json.dumps(step.depends_on),
                            _safe_json(step.args) or "{}",
                            _safe_json(step.result),
                            step.error,
                            _epoch_to_dt(step.started_at),
                            _epoch_to_dt(step.finished_at),
                        )
        except Exception:
            log.exception(
                "upsert_steps_bulk failed for run %s (non-fatal)", run_id,
            )

    # ── Approvals ─────────────────────────────────────────────────────────────

    async def create_approval_request(
        self,
        org_id: str,
        run_id: str,
        step_id: str,
    ) -> None:
        """Insert a pending approval row. Idempotent (conflict → no-op). Best-effort."""
        org_uuid = _parse_org_id(org_id)
        if org_uuid is None:
            return
        approval_id = f"{run_id}:{step_id}"
        try:
            async with get_pool().acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO automation_approvals
                        (organization_id, run_id, step_id, approval_id, status)
                    VALUES ($1, $2, $3, $4, 'pending')
                    ON CONFLICT (approval_id) DO NOTHING
                    """,
                    org_uuid, run_id, step_id, approval_id,
                )
        except Exception:
            log.exception(
                "create_approval_request failed for %s (non-fatal)", approval_id,
            )

    async def record_approval_decision(
        self,
        approval_id: str,
        status: str,
        decided_by: UUID | None,
    ) -> None:
        """Update approval row to approved/rejected/orphaned.

        This is NOT best-effort: the caller (the workflow_api approve/reject
        endpoint) must know whether the DB write succeeded before calling Engine
        A's approval registry. Exceptions propagate to the router.
        """
        if status not in ("approved", "rejected", "orphaned", "expired"):
            raise ValueError(f"Invalid approval status: {status!r}")
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                """
                UPDATE automation_approvals
                SET status     = $2,
                    decided_at = now(),
                    decided_by = $3
                WHERE approval_id = $1
                """,
                approval_id, status, decided_by,
            )
            # "UPDATE N" — N=0 means the row doesn't exist (ad-hoc run or pre-Gate-3 run)
            # which is acceptable; we still proceed to unblock Engine A.
            log.debug("record_approval_decision: %s → %s (%s)", approval_id, status, result)

    # ── Startup recovery ──────────────────────────────────────────────────────

    async def mark_interrupted_runs(self) -> int:
        """
        Startup recovery: mark all persisted runs that were still 'running' or
        'compensating' when the server last stopped as 'interrupted'.

        Engine A's in-memory state vanishes on process exit. Any run recorded
        as 'running' or 'compensating' in the DB has no live Engine A coroutine
        behind it and will never reach a terminal state on its own.

        Unlike recover_stale_builds() which uses a 30-minute threshold, here we
        mark ALL such runs immediately — there is no Engine A reconnection path
        that could resume them on the same process startup. A threshold only
        delays acknowledgment of a fact that is already certain: the engine died.
        """
        try:
            async with get_pool().acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE automation_runs
                    SET status      = 'interrupted',
                        finished_at = now(),
                        error       = 'Run interrupted — server restarted before completion'
                    WHERE status IN ('running', 'compensating')
                    """
                )
            # asyncpg returns "UPDATE N" as a string
            count = int(result.split()[-1]) if result else 0
            if count:
                log.warning(
                    "startup recovery: marked %d automation run(s) as interrupted", count,
                )
            return count
        except Exception:
            log.exception("mark_interrupted_runs failed (non-fatal)")
            return 0


# ── Singleton ─────────────────────────────────────────────────────────────────

_persistence: AutomationPersistence | None = None


def get_automation_persistence() -> AutomationPersistence:
    global _persistence
    if _persistence is None:
        _persistence = AutomationPersistence()
    return _persistence
