"""
Automation REST API — Phase 5 Gate 3.

Definitions:
  GET    /api/automations                  list (paginated, org-scoped)
  POST   /api/automations                  create
  GET    /api/automations/{id}             get
  PUT    /api/automations/{id}             update
  DELETE /api/automations/{id}             soft-delete
  POST   /api/automations/{id}/activate    set is_active=true
  POST   /api/automations/{id}/deactivate  set is_active=false

Runs:
  GET    /api/automation-runs              list (paginated, org-scoped)
  POST   /api/automation-runs             trigger (enqueue) a run
  GET    /api/automation-runs/{run_id}    get run + steps
  POST   /api/automation-runs/{run_id}/cancel  cancel a pending run

Security:
  • Every endpoint requires a verified OrgContext (X-Organization-Id + membership).
  • Read endpoints require automation:read permission.
  • Write/mutate endpoints require automation:write permission.
  • All queries filter by organization_id — no IDOR possible.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.db import get_pool
from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automations", tags=["automations"])
runs_router = APIRouter(prefix="/api/automation-runs", tags=["automation-runs"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _not_found(detail: str = "Not found") -> HTTPException:
    """404 (not 403) so callers cannot probe which org ids exist."""
    return HTTPException(404, detail)


async def _get_definition(conn, definition_id: str, org_id: str) -> dict:
    """Fetch a definition row scoped to org. Raises 404 if absent/deleted/other-org."""
    try:
        uid = uuid.UUID(definition_id)
    except ValueError:
        raise _not_found()
    row = await conn.fetchrow(
        "SELECT * FROM automation_definitions "
        "WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL",
        uid, uuid.UUID(org_id),
    )
    if row is None:
        raise _not_found()
    return dict(row)


def _row_to_definition(row: dict) -> dict:
    """Convert a DB row to the API shape."""
    return {
        "id":              str(row["id"]),
        "organization_id": str(row["organization_id"]),
        "name":            row["name"],
        "description":     row["description"],
        "definition":      row["definition"] if isinstance(row["definition"], dict) else {},
        "triggers":        row["triggers"] if isinstance(row["triggers"], list) else [],
        "is_active":       row["is_active"],
        "version":         row["version"],
        "created_by":      str(row["created_by"]) if row["created_by"] else None,
        "updated_by":      str(row["updated_by"]) if row["updated_by"] else None,
        "created_at":      row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at":      row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _row_to_run(row: dict, steps: list[dict] | None = None) -> dict:
    out: dict[str, Any] = {
        "id":              str(row["id"]),
        "organization_id": str(row["organization_id"]),
        "definition_id":   str(row["definition_id"]) if row.get("definition_id") else None,
        "run_id":          row["run_id"],
        "name":            row["name"],
        "status":          row["status"],
        "context":         row["context"] if isinstance(row["context"], dict) else {},
        "error":           row["error"],
        "triggered_by":    row["triggered_by"],
        "triggered_by_user": str(row["triggered_by_user"]) if row.get("triggered_by_user") else None,
        "created_at":      row["created_at"].isoformat() if row.get("created_at") else None,
        "started_at":      row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at":     row["finished_at"].isoformat() if row.get("finished_at") else None,
    }
    if steps is not None:
        out["steps"] = steps
    return out


def _row_to_step(row: dict) -> dict:
    return {
        "id":               str(row["id"]),
        "run_id":           row["run_id"],
        "step_id":          row["step_id"],
        "name":             row["name"],
        "status":           row["status"],
        "attempt":          row["attempt"],
        "requires_approval": row["requires_approval"],
        "depends_on":       row["depends_on"] if isinstance(row["depends_on"], list) else [],
        "args":             row["args"] if isinstance(row["args"], dict) else {},
        "result":           row["result"],
        "error":            row["error"],
        "started_at":       row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at":      row["finished_at"].isoformat() if row.get("finished_at") else None,
    }


# ---------------------------------------------------------------------------
# Definition schemas
# ---------------------------------------------------------------------------

class DefinitionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    definition: dict = {}
    triggers: list = []
    is_active: bool = False


class DefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[dict] = None
    triggers: Optional[list] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Definition endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_definitions(
    ctx: OrgContext = Depends(require_permission("automation", "read")),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        where = "WHERE organization_id = $1 AND deleted_at IS NULL"
        params: list = [uuid.UUID(ctx.org_id)]
        if active_only:
            where += " AND is_active = true"
        rows = await conn.fetch(
            f"SELECT * FROM automation_definitions {where} "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            *params, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM automation_definitions {where}", *params,
        )
    return {
        "items":  [_row_to_definition(dict(r)) for r in rows],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.post("", status_code=201)
async def create_definition(
    body: DefinitionCreate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        # Enforce unique name within org (defense-in-depth beyond DB constraint)
        existing = await conn.fetchval(
            "SELECT id FROM automation_definitions "
            "WHERE organization_id = $1 AND name = $2 AND deleted_at IS NULL",
            uuid.UUID(ctx.org_id), body.name,
        )
        if existing:
            raise HTTPException(409, f"An automation named {body.name!r} already exists")
        row = await conn.fetchrow(
            """
            INSERT INTO automation_definitions
                (organization_id, name, description, definition, triggers, is_active, created_by, updated_by)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $7)
            RETURNING *
            """,
            uuid.UUID(ctx.org_id),
            body.name,
            body.description,
            json.dumps(body.definition),
            json.dumps(body.triggers),
            body.is_active,
            uuid.UUID(ctx.user_id),
        )
    return _row_to_definition(dict(row))


@router.get("/{definition_id}")
async def get_definition(
    definition_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _get_definition(conn, definition_id, ctx.org_id)
    return _row_to_definition(row)


@router.put("/{definition_id}")
async def update_definition(
    definition_id: str,
    body: DefinitionUpdate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        # raises 404 if not found or wrong org
        await _get_definition(conn, definition_id, ctx.org_id)
        # Build update fields
        sets = ["updated_at = now()", "updated_by = $3", "version = version + 1"]
        params: list = [uuid.UUID(definition_id), uuid.UUID(ctx.org_id), uuid.UUID(ctx.user_id)]
        idx = 4

        if body.name is not None:
            sets.append(f"name = ${idx}")
            params.append(body.name)
            idx += 1
        if body.description is not None:
            sets.append(f"description = ${idx}")
            params.append(body.description)
            idx += 1
        if body.definition is not None:
            sets.append(f"definition = ${idx}::jsonb")
            params.append(json.dumps(body.definition))
            idx += 1
        if body.triggers is not None:
            sets.append(f"triggers = ${idx}::jsonb")
            params.append(json.dumps(body.triggers))
            idx += 1
        if body.is_active is not None:
            sets.append(f"is_active = ${idx}")
            params.append(body.is_active)
            idx += 1

        updated = await conn.fetchrow(
            f"UPDATE automation_definitions SET {', '.join(sets)} "
            "WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL RETURNING *",
            *params,
        )
        if updated is None:
            raise _not_found()
    return _row_to_definition(dict(updated))


@router.delete("/{definition_id}", status_code=204)
async def delete_definition(
    definition_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE automation_definitions SET deleted_at = now(), is_active = false "
            "WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL",
            uuid.UUID(definition_id) if _valid_uuid(definition_id) else uuid.uuid4(),
            uuid.UUID(ctx.org_id),
        )
    if result == "UPDATE 0":
        raise _not_found()


@router.post("/{definition_id}/activate")
async def activate_definition(
    definition_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE automation_definitions SET is_active = true, updated_at = now() "
            "WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL RETURNING *",
            uuid.UUID(definition_id) if _valid_uuid(definition_id) else uuid.uuid4(),
            uuid.UUID(ctx.org_id),
        )
    if row is None:
        raise _not_found()
    return _row_to_definition(dict(row))


@router.post("/{definition_id}/deactivate")
async def deactivate_definition(
    definition_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE automation_definitions SET is_active = false, updated_at = now() "
            "WHERE id = $1 AND organization_id = $2 AND deleted_at IS NULL RETURNING *",
            uuid.UUID(definition_id) if _valid_uuid(definition_id) else uuid.uuid4(),
            uuid.UUID(ctx.org_id),
        )
    if row is None:
        raise _not_found()
    return _row_to_definition(dict(row))


# ---------------------------------------------------------------------------
# Run schemas
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    definition_id: Optional[str] = None
    name: str = "manual-run"
    context: dict = {}
    triggered_by: str = "manual"


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------

@runs_router.get("")
async def list_runs(
    ctx: OrgContext = Depends(require_permission("automation", "read")),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    definition_id: Optional[str] = Query(None),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        where_clauses = ["organization_id = $1"]
        params: list = [uuid.UUID(ctx.org_id)]
        idx = 2

        if status:
            where_clauses.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if definition_id and _valid_uuid(definition_id):
            where_clauses.append(f"definition_id = ${idx}")
            params.append(uuid.UUID(definition_id))
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses)
        rows = await conn.fetch(
            f"SELECT * FROM automation_runs {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, offset,
        )
        total = await conn.fetchval(f"SELECT COUNT(*) FROM automation_runs {where}", *params)
    return {
        "items":  [_row_to_run(dict(r)) for r in rows],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@runs_router.post("", status_code=202)
async def trigger_run(
    body: RunCreate,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    """Enqueue an automation run via the job queue.  Returns the run_id immediately."""
    from app.core.jobs import get_job_queue

    run_id = str(uuid.uuid4())

    # Store a pending record before enqueuing so the client can poll.
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO automation_runs
                (organization_id, definition_id, run_id, name, status,
                 context, triggered_by, triggered_by_user)
            VALUES ($1, $2, $3, $4, 'pending', $5::jsonb, $6, $7)
            """,
            uuid.UUID(ctx.org_id),
            uuid.UUID(body.definition_id) if body.definition_id and _valid_uuid(body.definition_id) else None,
            run_id,
            body.name,
            json.dumps(body.context),
            body.triggered_by,
            uuid.UUID(ctx.user_id),
        )

    # Enqueue via existing job queue — automation handler will be registered
    # by the scheduler module at startup.
    payload = {
        "organization_id": ctx.org_id,
        "run_id": run_id,
        "definition_id": body.definition_id,
        "context": body.context,
        "triggered_by": body.triggered_by,
        "triggered_by_user": ctx.user_id,
    }
    await get_job_queue().submit(
        "automation.trigger.manual",
        payload=payload,
        org_id=ctx.org_id,  # overwrites payload org_id with server-verified value
        idempotency_key=run_id,
    )

    return {"run_id": run_id, "status": "pending"}


@runs_router.get("/{run_id}")
async def get_run(
    run_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "read")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM automation_runs WHERE run_id = $1 AND organization_id = $2",
            run_id, uuid.UUID(ctx.org_id),
        )
        if row is None:
            raise _not_found()
        step_rows = await conn.fetch(
            "SELECT * FROM automation_run_steps WHERE run_id = $1 AND organization_id = $2 ORDER BY created_at",
            run_id, uuid.UUID(ctx.org_id),
        )
    steps = [_row_to_step(dict(s)) for s in step_rows]
    return _row_to_run(dict(row), steps=steps)


@runs_router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    ctx: OrgContext = Depends(require_permission("automation", "write")),
):
    """Cancel a pending run.  Running runs are not forcibly cancelled (engine is in-memory)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE automation_runs SET status = 'cancelled', finished_at = now() "
            "WHERE run_id = $1 AND organization_id = $2 AND status = 'pending'",
            run_id, uuid.UUID(ctx.org_id),
        )
    if result == "UPDATE 0":
        # Either already running/finished or wrong org — same 404 shape.
        raise HTTPException(409, "Run is not in a cancellable state")
    return {"run_id": run_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False
