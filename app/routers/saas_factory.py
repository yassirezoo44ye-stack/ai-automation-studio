"""
SaaS Factory — REST router.

Endpoints (all require JWT auth + org membership):
  POST   /api/saas-factory/projects          Submit idea, start pipeline
  GET    /api/saas-factory/projects          List org's projects
  GET    /api/saas-factory/projects/{id}     Project detail + phase + checkpoint
  POST   /api/saas-factory/projects/{id}/resume  Resume a FAILED project
  DELETE /api/saas-factory/projects/{id}     Cancel / delete project

Security:
  • Every endpoint resolves OrgContext — membership verified in DB.
  • All writes are scoped to ctx.org_id, never from the request body.
  • project_id + org_id checked together (IDOR prevention).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.tenancy import OrgContext, require_permission
from app.saas_factory.pipeline import get_pipeline

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/saas-factory", tags=["saas-factory"])


# ── Request / response models ─────────────────────────────────────────────────

class SubmitIdeaRequest(BaseModel):
    idea: str = Field(min_length=10, max_length=3000)


class ProjectSummary(BaseModel):
    id: str
    idea_text: str
    phase: str
    app_builder_app_id: Optional[str]
    flow_creation_id: Optional[str]
    error_message: Optional[str]
    started_at: str
    updated_at: str
    completed_at: Optional[str]


class ProjectDetail(ProjectSummary):
    checkpoint: dict[str, Any]


# ── Helpers ───────────────────────────────────────────────────────────────────

from app.core.db import get_pool  # noqa: E402 — post-import avoids circular deps


def _row_to_summary(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "idea_text": row["idea_text"],
        "phase": row["phase"],
        "app_builder_app_id": str(row["app_builder_app_id"]) if row.get("app_builder_app_id") else None,
        "flow_creation_id": str(row["flow_creation_id"]) if row.get("flow_creation_id") else None,
        "error_message": row.get("error_message"),
        "started_at": row["started_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/projects", status_code=202)
async def submit_idea(
    body: SubmitIdeaRequest,
    ctx: OrgContext = Depends(require_permission("saas_factory", "create")),
) -> dict:
    """Submit a natural-language idea and start the SaaS Factory pipeline."""
    project_id = str(uuid.uuid4())
    pipeline = get_pipeline()
    await pipeline.start(
        project_id=project_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        idea_text=body.idea,
    )
    return {
        "project_id": project_id,
        "phase": "IDEA",
        "message": "Pipeline started. Poll GET /api/saas-factory/projects/{id} for progress.",
    }


@router.get("/projects")
async def list_projects(
    ctx: OrgContext = Depends(require_permission("saas_factory", "read")),
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, idea_text, phase, app_builder_app_id, flow_creation_id, "
            "error_message, started_at, updated_at, completed_at "
            "FROM saas_factory_projects WHERE org_id=$1 "
            "ORDER BY started_at DESC LIMIT 50",
            uuid.UUID(ctx.org_id),
        )
    return {"projects": [_row_to_summary(dict(r)) for r in rows]}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    ctx: OrgContext = Depends(require_permission("saas_factory", "read")),
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, idea_text, phase, checkpoint, app_builder_app_id, "
            "flow_creation_id, error_message, started_at, updated_at, completed_at "
            "FROM saas_factory_projects WHERE id=$1 AND org_id=$2",
            uuid.UUID(project_id), uuid.UUID(ctx.org_id),
        )
    if not row:
        raise HTTPException(404, "Project not found")
    result = _row_to_summary(dict(row))
    raw_cp = row["checkpoint"]
    result["checkpoint"] = json.loads(raw_cp) if isinstance(raw_cp, str) else (raw_cp or {})
    return result


@router.post("/projects/{project_id}/resume", status_code=202)
async def resume_project(
    project_id: str,
    ctx: OrgContext = Depends(require_permission("saas_factory", "update")),
) -> dict:
    pipeline = get_pipeline()
    try:
        result = await pipeline.resume(
            project_id=project_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    ctx: OrgContext = Depends(require_permission("saas_factory", "delete")),
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM saas_factory_projects WHERE id=$1 AND org_id=$2",
            uuid.UUID(project_id), uuid.UUID(ctx.org_id),
        )
    if deleted == "DELETE 0":
        raise HTTPException(404, "Project not found")
