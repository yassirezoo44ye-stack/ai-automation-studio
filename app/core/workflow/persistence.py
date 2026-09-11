"""
Automation Persistence Adapter — Phase 5 Gate 3.

Side-channel adapter that persists Engine A (app.core.workflow.engine)
WorkflowRun / WorkflowStep state to PostgreSQL without modifying the engine.

RULES enforced here:
  • NEVER persist callables, coroutines, asyncio.Event, or any executable object.
  • NEVER use pickle / eval / exec.
  • Non-JSON-native values are coerced to a safe representation dict.
  • Epoch floats from engine timestamps → datetime (UTC-aware) for TIMESTAMPTZ.
  • Invalid/malformed organization_id → log warning + skip, never guess another tenant.
  • Persistence failures in the normal run path are best-effort (log + continue).
  • Approval decision persistence is DB-first (raises on DB failure).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.db import get_pool

log = logging.getLogger(__name__)

UTC = timezone.utc

# Types that cannot be safely serialized to JSON.  We detect these by type
# name rather than isinstance() to avoid importing asyncio/other runtime
# modules just to check — the runtime is pure-asyncio and we never want a
# circular dependency or ImportError inside a persistence layer.
_UNSAFE_TYPE_NAMES = frozenset({
    "function", "coroutine", "coroutinefunction", "method",
    "builtin_function_or_method", "Event", "Lock", "Semaphore",
    "Task", "Future",
})


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _safe_json_value(val: Any, *, _depth: int = 0) -> Any:
    """Recursively convert `val` to a JSON-safe representation.

    Non-serializable types become:
        {"value": str(val), "type": "TypeName", "coerced": true}

    Maximum recursion depth: 10 (protects against deeply nested engine state).
    """
    if _depth > 10:
        return {"value": "...(truncated)", "type": "deep_nest", "coerced": True}

    # Already JSON-native
    if val is None or isinstance(val, (bool, int, float, str)):
        return val

    # Callable / coroutine / asyncio primitives → safe sentinel
    type_name = type(val).__name__
    if type_name in _UNSAFE_TYPE_NAMES or callable(val):
        return {"value": repr(val)[:120], "type": type_name, "coerced": True}

    if isinstance(val, dict):
        return {str(k): _safe_json_value(v, _depth=_depth + 1) for k, v in val.items()}

    if isinstance(val, (list, tuple, set, frozenset)):
        return [_safe_json_value(v, _depth=_depth + 1) for v in val]

    if isinstance(val, datetime):
        return val.isoformat()

    if isinstance(val, uuid.UUID):
        return str(val)

    # Dataclass / plain object with __dict__
    if hasattr(val, "__dict__"):
        return {
            "value": {str(k): _safe_json_value(v, _depth=_depth + 1)
                      for k, v in val.__dict__.items()},
            "type": type_name,
            "coerced": True,
        }

    # Fallback: convert to string
    try:
        return {"value": str(val)[:256], "type": type_name, "coerced": True}
    except Exception:
        return {"value": "<unrepresentable>", "type": type_name, "coerced": True}


def safe_json(val: Any) -> Any:
    """Return a JSON-serializable representation of `val`."""
    return _safe_json_value(val)


def serialize_context(ctx: dict) -> str:
    """Sanitize an engine context dict and return a JSON string.
    Keys prefixed with '_' that hold non-serializable values are dropped
    after logging so organisation data is preserved but runtime artifacts are not.
    """
    safe: dict[str, Any] = {}
    for k, v in (ctx or {}).items():
        try:
            safe[str(k)] = _safe_json_value(v)
        except Exception:
            log.debug("context serialization: dropping key %r", k)
    try:
        return json.dumps(safe)
    except Exception as exc:
        log.warning("context serialization failed: %s — persisting empty context", exc)
        return "{}"


def _epoch_to_dt(ts: Optional[float]) -> Optional[datetime]:
    """Convert an engine epoch float to a UTC-aware datetime, or None."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _parse_org_id(raw: Any) -> Optional[str]:
    """Safely parse and validate an organization_id.
    Returns a canonical UUID string, or None if invalid/missing.
    Never raises — an invalid org_id is logged and returned as None so the
    caller can skip persistence rather than guess a different tenant.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return str(uuid.UUID(s))
    except ValueError:
        log.warning(
            "persistence: malformed organization_id %r — skipping persistence for this record",
            s[:60],
        )
        return None


def _result_to_json(result: Any) -> Optional[str]:
    """Serialize a step result to a JSON string, or None on failure."""
    if result is None:
        return None
    safe = _safe_json_value(result)
    try:
        return json.dumps(safe)
    except Exception:
        return json.dumps({"value": str(result)[:256], "coerced": True})


# ---------------------------------------------------------------------------
# Run persistence
# ---------------------------------------------------------------------------

async def upsert_run(run: Any, organization_id: str) -> None:
    """Persist or update an engine WorkflowRun record.

    `run` is a WorkflowRun dataclass from app.core.workflow.engine.
    `organization_id` is the verified org_id from OrgContext — not taken
    from run.context to prevent a client-supplied value from crossing tenants.

    Best-effort: logs on failure, does not raise (except for programming
    errors like a None pool during startup which should propagate).
    """
    org_id = _parse_org_id(organization_id)
    if org_id is None:
        log.warning("upsert_run: invalid org_id, skipping run_id=%s", getattr(run, "run_id", "?"))
        return

    try:
        ctx_json  = serialize_context(getattr(run, "context", {}))
        status    = getattr(run, "status", None)
        status_v  = status.value if hasattr(status, "value") else str(status)

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO automation_runs
                    (organization_id, run_id, name, status, context, error,
                     created_at, started_at, finished_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
                ON CONFLICT (run_id) DO UPDATE SET
                    status      = EXCLUDED.status,
                    context     = EXCLUDED.context,
                    error       = EXCLUDED.error,
                    started_at  = COALESCE(automation_runs.started_at, EXCLUDED.started_at),
                    finished_at = EXCLUDED.finished_at
                """,
                org_id,
                run.run_id,
                getattr(run, "name", ""),
                status_v,
                ctx_json,
                getattr(run, "error", None),
                _epoch_to_dt(getattr(run, "created_at", None)) or datetime.now(UTC),
                _epoch_to_dt(getattr(run, "started_at", None)),
                _epoch_to_dt(getattr(run, "finished_at", None)),
            )
    except Exception:
        log.warning("upsert_run failed for run_id=%s", getattr(run, "run_id", "?"), exc_info=True)


async def set_run_definition(run_id: str, definition_id: str,
                             triggered_by: Optional[str] = None,
                             triggered_by_user: Optional[str] = None) -> None:
    """Link a run to its definition after creation (fire-and-forget)."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE automation_runs
                SET definition_id      = $2,
                    triggered_by       = $3,
                    triggered_by_user  = $4
                WHERE run_id = $1
                """,
                run_id,
                uuid.UUID(definition_id) if definition_id else None,
                triggered_by,
                uuid.UUID(triggered_by_user) if triggered_by_user else None,
            )
    except Exception:
        log.warning("set_run_definition failed run_id=%s", run_id, exc_info=True)


# ---------------------------------------------------------------------------
# Step persistence
# ---------------------------------------------------------------------------

async def upsert_step(run_id: str, organization_id: str, step: Any) -> None:
    """Persist or update a single engine WorkflowStep record.

    Only serializable fields are persisted.  Callables (fn, condition,
    compensation_fn) and asyncio.Event are deliberately excluded.
    """
    org_id = _parse_org_id(organization_id)
    if org_id is None:
        return

    try:
        status   = getattr(step, "status", None)
        status_v = status.value if hasattr(status, "value") else str(status)

        result_json   = _result_to_json(getattr(step, "result", None))
        args_json     = json.dumps(_safe_json_value(getattr(step, "args", {})))
        depends_json  = json.dumps(list(getattr(step, "depends_on", [])))

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO automation_run_steps
                    (organization_id, run_id, step_id, name, status, attempt,
                     requires_approval, depends_on, args, result, error,
                     created_at, started_at, finished_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb,
                        $10::jsonb, $11, now(), $12, $13)
                ON CONFLICT (run_id, step_id) DO UPDATE SET
                    status           = EXCLUDED.status,
                    attempt          = EXCLUDED.attempt,
                    result           = EXCLUDED.result,
                    error            = EXCLUDED.error,
                    started_at       = COALESCE(automation_run_steps.started_at, EXCLUDED.started_at),
                    finished_at      = EXCLUDED.finished_at
                """,
                org_id,
                run_id,
                step.id,
                getattr(step, "name", ""),
                status_v,
                getattr(step, "attempt", 0),
                bool(getattr(step, "requires_approval", False)),
                depends_json,
                args_json,
                result_json,
                getattr(step, "error", None),
                _epoch_to_dt(getattr(step, "started_at", None)),
                _epoch_to_dt(getattr(step, "finished_at", None)),
            )
    except Exception:
        log.warning("upsert_step failed run_id=%s step_id=%s",
                    run_id, getattr(step, "id", "?"), exc_info=True)


async def upsert_steps_bulk(run_id: str, organization_id: str, steps: dict) -> None:
    """Persist all steps for a run in one connection acquisition.

    `steps` is the WorkflowRun.steps dict (step_id → WorkflowStep).
    Individual step failures are logged but do not abort the batch.
    """
    org_id = _parse_org_id(organization_id)
    if org_id is None:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        for step in steps.values():
            try:
                status   = getattr(step, "status", None)
                status_v = status.value if hasattr(status, "value") else str(status)

                result_json  = _result_to_json(getattr(step, "result", None))
                args_json    = json.dumps(_safe_json_value(getattr(step, "args", {})))
                depends_json = json.dumps(list(getattr(step, "depends_on", [])))

                await conn.execute(
                    """
                    INSERT INTO automation_run_steps
                        (organization_id, run_id, step_id, name, status, attempt,
                         requires_approval, depends_on, args, result, error,
                         created_at, started_at, finished_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb,
                            $10::jsonb, $11, now(), $12, $13)
                    ON CONFLICT (run_id, step_id) DO UPDATE SET
                        status      = EXCLUDED.status,
                        attempt     = EXCLUDED.attempt,
                        result      = EXCLUDED.result,
                        error       = EXCLUDED.error,
                        started_at  = COALESCE(automation_run_steps.started_at, EXCLUDED.started_at),
                        finished_at = EXCLUDED.finished_at
                    """,
                    org_id,
                    run_id,
                    step.id,
                    getattr(step, "name", ""),
                    status_v,
                    getattr(step, "attempt", 0),
                    bool(getattr(step, "requires_approval", False)),
                    depends_json,
                    args_json,
                    result_json,
                    getattr(step, "error", None),
                    _epoch_to_dt(getattr(step, "started_at", None)),
                    _epoch_to_dt(getattr(step, "finished_at", None)),
                )
            except Exception:
                log.warning("upsert_steps_bulk: step %s failed",
                            getattr(step, "id", "?"), exc_info=True)


# ---------------------------------------------------------------------------
# Approval persistence
# ---------------------------------------------------------------------------

async def create_approval_request(
    organization_id: str,
    run_id: str,
    step_id: str,
) -> Optional[str]:
    """Insert a new pending approval record.

    approval_id format: "{run_id}:{step_id}" — compatible with Engine A's
    ApprovalRegistry key format.

    Returns the approval_id on success, None on failure.
    Idempotent via ON CONFLICT DO NOTHING (duplicate calls are safe).
    """
    org_id = _parse_org_id(organization_id)
    if org_id is None:
        return None

    approval_id = f"{run_id}:{step_id}"
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO automation_approvals
                    (organization_id, run_id, step_id, approval_id, status)
                VALUES ($1, $2, $3, $4, 'pending')
                ON CONFLICT (approval_id) DO NOTHING
                """,
                org_id, run_id, step_id, approval_id,
            )
        return approval_id
    except Exception:
        log.error("create_approval_request failed run_id=%s step_id=%s",
                  run_id, step_id, exc_info=True)
        return None


async def record_approval_decision(
    approval_id: str,
    status: str,            # 'approved' | 'rejected' | 'orphaned'
    decided_by: Optional[str] = None,
) -> bool:
    """Persist an approval decision.

    DB-FIRST: raises on failure so callers know the decision was not saved.
    Returns True on success, False if the approval record was not found.
    """
    if status not in ("approved", "rejected", "orphaned"):
        raise ValueError(f"Invalid approval status: {status!r}")

    try:
        decided_by_uuid = uuid.UUID(decided_by) if decided_by else None
    except ValueError:
        decided_by_uuid = None

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            UPDATE automation_approvals
            SET status     = $2,
                decided_at = now(),
                decided_by = $3
            WHERE approval_id = $1
              AND status = 'pending'
            RETURNING id
            """,
            approval_id, status, decided_by_uuid,
        )
    return result is not None


async def get_approval_org(approval_id: str) -> Optional[str]:
    """Look up the organization_id for an approval record.
    Used to verify org ownership before mutating engine state.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT organization_id, status FROM automation_approvals WHERE approval_id = $1",
                approval_id,
            )
        if row is None:
            return None
        return str(row["organization_id"])
    except Exception:
        log.warning("get_approval_org failed for %s", approval_id, exc_info=True)
        return None
