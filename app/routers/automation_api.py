"""
Automation API — Phase 5 Gate 3.

REST/JSON endpoints for automation definitions and runs.
All endpoints require org_context (verified org membership).

Definitions
  GET    /api/automations                list definitions (paginated)
  POST   /api/automations               create definition
  GET    /api/automations/{id}          get definition
  PUT    /api/automations/{id}          update definition (bumps version)
  DELETE /api/automations/{id}          soft-delete definition
  POST   /api/automations/{id}/activate   set is_active=true
  POST   /api/automations/{id}/deactivate set is_active=false

Runs
  GET  /api/automation-runs             list runs (paginated)
  POST /api/automation-runs             launch a run from definition_id
  GET  /api/automation-runs/{run_id}    get run + steps
  POST /api/automation-runs/{run_id}/cancel  cancel a running run

Security
  - Every query includes AND organization_id = $<n> — no IDOR possible.
  - organization_id always comes from the authenticated OrgContext, never
    from the request body.
  - created_by / updated_by come from ctx.user_id.
  - require_permission("automation", "read") / ("automation", "write") enforce
    role-based access on top of org membership.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.db import get_pool
from app.core.workflow.engine import (
    WorkflowBuilder,
    WorkflowStatus,
    get_workflow_engine,
)
from app.core.workflow.persistence import get_automation_persistence
from app.plugins.workflow_nodes import get_workflow_node_registry
from app.tenancy.context import OrgContext, org_context, require_permission

log = logging.getLogger(__name__)

router = APIRouter(tags=["automation"])

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


# ── Request / response models ──────────────────────────────────────────────────

class DefinitionCreate(BaseModel):
    name: str
    description: str = ""
    definition: dict = {}
    triggers: list = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("definition")
    @classmethod
    def definition_is_dict(cls, v: object) -> dict:
        if not isinstance(v, dict):
            raise ValueError("definition must be a JSON object")
        return v  # type: ignore[return-value]

    @field_validator("triggers")
    @classmethod
    def triggers_is_list(cls, v: object) -> list:
        if not isinstance(v, list):
            raise ValueError("triggers must be a JSON array")
        return v  # type: ignore[return-value]


class DefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict | None = None
    triggers: list | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("name must not be empty")
        return v


class RunCreate(BaseModel):
    definition_id: str
    context: dict = {}


# ── Helper: org-scoped lookup ──────────────────────────────────────────────────

async def _get_definition(def_id: str, org_id: str) -> dict:
    """Fetch an automation definition scoped to org_id. 404 if not found."""
    try:
        uid = uuid.UUID(def_id)
    except ValueError:
        raise HTTPException(404, "Automation definition not found")
    org_uuid = uuid.UUID(org_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, name, description, definition,
                   triggers, is_active, version, created_by, updated_by,
                   created_at, updated_at
            FROM automation_definitions
            WHERE id = $1
              AND organization_id = $2
              AND deleted_at IS NULL
            """,
            uid, org_uuid,
        )
    if not row:
        raise HTTPException(404, "Automation definition not found")
    return dict(row)


def _row_to_def_dict(row: dict) -> dict:
    """Convert a DB row dict to a JSON-safe API response dict."""
    d = {k: v for k, v in row.items()}
    for field in ("id", "organization_id", "created_by", "updated_by"):
        if d.get(field) is not None:
            d[field] = str(d[field])
    for field in ("definition", "triggers"):
        v = d.get(field)
        if isinstance(v, str):
            d[field] = json.loads(v)
    for field in ("created_at", "updated_at"):
        if d.get(field) is not None:
            d[field] = d[field].isoformat()
    return d


def _row_to_run_dict(row: dict) -> dict:
    d = {k: v for k, v in row.items()}
    for field in ("id", "organization_id", "definition_id", "triggered_by_user"):
        if d.get(field) is not None:
            d[field] = str(d[field])
    for field in ("context",):
        v = d.get(field)
        if isinstance(v, str):
            d[field] = json.loads(v)
    for field in ("created_at", "started_at", "finished_at"):
        if d.get(field) is not None:
            d[field] = d[field].isoformat()
    return d


def _row_to_step_dict(row: dict) -> dict:
    d = {k: v for k, v in row.items()}
    for field in ("id", "organization_id"):
        if d.get(field) is not None:
            d[field] = str(d[field])
    for field in ("depends_on", "args", "result"):
        v = d.get(field)
        if isinstance(v, str):
            try:
                d[field] = json.loads(v)
            except Exception:
                pass
    for field in ("started_at", "finished_at", "created_at"):
        if d.get(field) is not None:
            d[field] = d[field].isoformat()
    return d


# ── Definitions ────────────────────────────────────────────────────────────────

@router.get("/api/automations")
async def list_definitions(
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, name, description, definition,
                   triggers, is_active, version, created_by, updated_by,
                   created_at, updated_at
            FROM automation_definitions
            WHERE organization_id = $1
              AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT $2 OFFSET $3
            """,
            org_uuid, limit, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM automation_definitions WHERE organization_id=$1 AND deleted_at IS NULL",
            org_uuid,
        )
    return {
        "items": [_row_to_def_dict(dict(r)) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/api/automations", status_code=201)
async def create_definition(
    body: DefinitionCreate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    org_uuid = uuid.UUID(ctx.org_id)
    user_uuid = uuid.UUID(ctx.user_id)
    async with get_pool().acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO automation_definitions
                    (organization_id, name, description, definition, triggers,
                     is_active, version, created_by, updated_by)
                VALUES ($1,$2,$3,$4,$5,true,1,$6,$6)
                RETURNING id, organization_id, name, description, definition,
                          triggers, is_active, version, created_by, updated_by,
                          created_at, updated_at
                """,
                org_uuid,
                body.name,
                body.description,
                json.dumps(body.definition),
                json.dumps(body.triggers),
                user_uuid,
            )
        except Exception as exc:
            if "idx_automation_defs_name_org" in str(exc) or "unique" in str(exc).lower():
                raise HTTPException(409, f"An automation named {body.name!r} already exists in this organization")
            raise
    return _row_to_def_dict(dict(row))


@router.get("/api/automations/{def_id}")
async def get_definition(
    def_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    row = await _get_definition(def_id, ctx.org_id)
    return _row_to_def_dict(row)


@router.put("/api/automations/{def_id}")
async def update_definition(
    def_id: str,
    body: DefinitionUpdate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    # Verify ownership first
    await _get_definition(def_id, ctx.org_id)
    uid = uuid.UUID(def_id)
    org_uuid = uuid.UUID(ctx.org_id)
    user_uuid = uuid.UUID(ctx.user_id)

    # Build partial update — only touch provided fields
    sets = ["version = version + 1", "updated_at = now()", "updated_by = $3"]
    params: list = [uid, org_uuid, user_uuid]
    i = 4
    if body.name is not None:
        sets.append(f"name = ${i}")
        params.append(body.name)
        i += 1
    if body.description is not None:
        sets.append(f"description = ${i}")
        params.append(body.description)
        i += 1
    if body.definition is not None:
        sets.append(f"definition = ${i}")
        params.append(json.dumps(body.definition))
        i += 1
    if body.triggers is not None:
        sets.append(f"triggers = ${i}")
        params.append(json.dumps(body.triggers))
        i += 1

    set_clause = ", ".join(sets)
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE automation_definitions
                SET {set_clause}
                WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL
                RETURNING id, organization_id, name, description, definition,
                          triggers, is_active, version, created_by, updated_by,
                          created_at, updated_at
                """,
                *params,
            )
    except Exception as exc:
        if "idx_automation_defs_name_org" in str(exc) or "unique" in str(exc).lower():
            raise HTTPException(409, f"An automation named {body.name!r} already exists in this organization")
        raise
    if not row:
        raise HTTPException(404, "Automation definition not found")
    return _row_to_def_dict(dict(row))


@router.delete("/api/automations/{def_id}", status_code=204)
async def delete_definition(
    def_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    await _get_definition(def_id, ctx.org_id)
    uid = uuid.UUID(def_id)
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE automation_definitions
            SET deleted_at = now(), updated_at = now()
            WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL
            """,
            uid, org_uuid,
        )


@router.post("/api/automations/{def_id}/activate")
async def activate_definition(
    def_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    await _get_definition(def_id, ctx.org_id)
    uid = uuid.UUID(def_id)
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE automation_definitions
            SET is_active = true, updated_at = now()
            WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL
            RETURNING id, is_active
            """,
            uid, org_uuid,
        )
    return {"id": str(row["id"]), "is_active": row["is_active"]}


@router.post("/api/automations/{def_id}/deactivate")
async def deactivate_definition(
    def_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    await _get_definition(def_id, ctx.org_id)
    uid = uuid.UUID(def_id)
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE automation_definitions
            SET is_active = false, updated_at = now()
            WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL
            RETURNING id, is_active
            """,
            uid, org_uuid,
        )
    return {"id": str(row["id"]), "is_active": row["is_active"]}


# ── Runs ───────────────────────────────────────────────────────────────────────

@router.get("/api/automation-runs")
async def list_runs(
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    definition_id: str | None = None,
    status: str | None = None,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)
    org_uuid = uuid.UUID(ctx.org_id)

    conditions = ["organization_id = $1"]
    params: list = [org_uuid]
    i = 2
    if definition_id:
        try:
            conditions.append(f"definition_id = ${i}")
            params.append(uuid.UUID(definition_id))
            i += 1
        except ValueError:
            pass
    if status:
        conditions.append(f"status = ${i}")
        params.append(status)
        i += 1

    where = " AND ".join(conditions)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, organization_id, definition_id, run_id, name, status,
                   context, error, triggered_by, triggered_by_user,
                   created_at, started_at, finished_at
            FROM automation_runs
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ${i} OFFSET ${i+1}
            """,
            *params, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM automation_runs WHERE {where}",
            *params,
        )
    return {
        "items": [_row_to_run_dict(dict(r)) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/api/automation-runs", status_code=201)
async def create_run(
    body: RunCreate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    """
    Launch an automation run from a stored definition.

    Steps:
    1. Authenticate + resolve org (done by require_permission)
    2. Load definition (org-scoped)
    3. Reject inactive/deleted definitions
    4. Build Engine A WorkflowRun from the blueprint
    5. Persist initial run record
    6. Execute via Engine A (non-blocking)
    7. Return the run record
    """
    # 1+2: Load definition with org scope
    def_row = await _get_definition(body.definition_id, ctx.org_id)
    if not def_row["is_active"]:
        raise HTTPException(422, "Cannot launch a run from an inactive automation definition")

    # 3: Build Engine A WorkflowRun from the blueprint
    blueprint = def_row["definition"]
    if isinstance(blueprint, str):
        blueprint = json.loads(blueprint)

    nodes = blueprint.get("nodes", {})
    start_node = blueprint.get("start_node_id")
    if not nodes:
        raise HTTPException(422, "Automation definition has no nodes")

    registry = get_workflow_node_registry()
    builder = WorkflowBuilder(def_row["name"])

    for node_id, node in nodes.items():
        fn_name = node.get("step_fn_name")
        if not fn_name:
            raise HTTPException(422, f"Node {node_id!r} has no step_fn_name")
        fn = registry.get_node(fn_name)
        if fn is None:
            raise HTTPException(422, f"Unknown workflow node function: {fn_name!r}")
        retry_cfg = node.get("retry") or {}
        from app.core.workflow.engine import RetryPolicy
        retry = RetryPolicy(
            max_attempts=int(retry_cfg.get("max_attempts", 3)),
            base_delay_s=float(retry_cfg.get("base_delay_s", 1.0)),
            max_delay_s=float(retry_cfg.get("max_delay_s", 30.0)),
        )
        builder.step(
            step_id=node_id,
            name=node.get("name", node_id),
            fn=fn,
            args=node.get("args", {}),
            depends_on=node.get("depends_on", []),
            retry=retry,
            timeout_s=node.get("timeout_s"),
            requires_approval=node.get("requires_approval", False),
        )

    run_context = {
        "organization_id": ctx.org_id,
        "definition_id": body.definition_id,
        **body.context,
    }
    run = builder.build(context=run_context)

    # 4: Persist initial run record (BEFORE execution so the ID is available)
    persistence = get_automation_persistence()
    await persistence.upsert_run(
        run,
        definition_id=body.definition_id,
        triggered_by="api",
        triggered_by_user=ctx.user_id,
    )
    # Persist initial steps
    await persistence.upsert_steps_bulk(run.run_id, ctx.org_id, run.steps)

    # 5: Execute via Engine A — fire and forget for long-running workflows
    engine = get_workflow_engine()

    async def _run_and_persist():
        try:
            result = await engine.execute(run, saga=True)
            await persistence.upsert_run(
                result,
                definition_id=body.definition_id,
                triggered_by="api",
                triggered_by_user=ctx.user_id,
            )
            await persistence.upsert_steps_bulk(result.run_id, ctx.org_id, result.steps)
        except Exception:
            log.exception("run_and_persist error for run %s (non-fatal)", run.run_id)

    import asyncio
    asyncio.create_task(_run_and_persist())

    return {
        "run_id": run.run_id,
        "definition_id": body.definition_id,
        "name": run.name,
        "status": run.status.value,
        "organization_id": ctx.org_id,
    }


@router.get("/api/automation-runs/{run_id}")
async def get_run(
    run_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, definition_id, run_id, name, status,
                   context, error, triggered_by, triggered_by_user,
                   created_at, started_at, finished_at
            FROM automation_runs
            WHERE run_id = $1 AND organization_id = $2
            """,
            run_id, org_uuid,
        )
        if not row:
            raise HTTPException(404, "Automation run not found")
        steps = await conn.fetch(
            """
            SELECT id, run_id, organization_id, step_id, name, status,
                   attempt, requires_approval, depends_on, args, result,
                   error, started_at, finished_at, created_at
            FROM automation_run_steps
            WHERE run_id = $1 AND organization_id = $2
            ORDER BY created_at ASC
            """,
            run_id, org_uuid,
        )
    result = _row_to_run_dict(dict(row))
    result["steps"] = [_row_to_step_dict(dict(s)) for s in steps]
    return result


@router.post("/api/automation-runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    """Cancel a running automation run.

    Checks org ownership in DB first, then attempts Engine A cancellation.
    If Engine A no longer has the run (restarted), marks DB status as
    'cancelled' directly.
    """
    org_uuid = uuid.UUID(ctx.org_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT run_id, status FROM automation_runs WHERE run_id=$1 AND organization_id=$2",
            run_id, org_uuid,
        )
    if not row:
        raise HTTPException(404, "Automation run not found")
    if row["status"] in ("completed", "failed", "cancelled", "interrupted"):
        return {"run_id": run_id, "status": row["status"], "cancelled": False,
                "message": f"Run already in terminal state: {row['status']}"}

    # Try Engine A cancellation (it may no longer have the run after a restart)
    engine = get_workflow_engine()
    cancelled = False
    for task_id, task in list(engine._active.items()):
        active_run = engine._active.get(run_id)
        if active_run and active_run.context.get("organization_id") == ctx.org_id:
            task.cancel()
            cancelled = True
            break

    # Update DB regardless
    final_status = "cancelled"
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE automation_runs
            SET status='cancelled', finished_at=now(),
                error='Cancelled by user'
            WHERE run_id=$1 AND organization_id=$2
              AND status NOT IN ('completed','failed','cancelled','interrupted')
            """,
            run_id, org_uuid,
        )
    return {"run_id": run_id, "status": final_status, "cancelled": True}
