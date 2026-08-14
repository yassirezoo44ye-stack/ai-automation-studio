"""
Engineering Missions API.

Endpoints:
  POST   /api/engineering/missions              — create mission
  GET    /api/engineering/missions              — list missions for org
  GET    /api/engineering/missions/{id}         — get mission + tasks
  DELETE /api/engineering/missions/{id}         — cancel mission
  GET    /api/engineering/missions/{id}/tasks   — list tasks
  GET    /api/engineering/missions/{id}/transitions — FSM audit trail
  POST   /api/engineering/missions/{id}/launch  — start Release Autopilot

Security:
  - org_id always from OrgContext (never from request body).
  - All endpoints require authentication and org membership (via org_context).
  - Mission creation requires "engineering" "create" permission.
  - Launch requires "engineering" "execute" permission.
  - Mission data is RLS-filtered at DB level.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engineering", tags=["engineering"])


# ── Request models ─────────────────────────────────────────────────────────────

class CreateMissionRequest(BaseModel):
    objective: str = Field(..., min_length=5, max_length=2000)
    template:  Optional[str] = Field(None, max_length=100)
    project_id: Optional[str] = None
    budget_tokens: Optional[int] = Field(None, ge=1000, le=1_000_000)
    budget_steps:  Optional[int] = Field(None, ge=1,    le=1000)

    @field_validator("objective")
    @classmethod
    def objective_no_injection(cls, v: str) -> str:
        # Prevent trivial prompt injection in the objective field
        lower = v.lower()
        if any(token in lower for token in ["ignore previous", "system:", "assistant:"]):
            raise ValueError("invalid objective")
        return v


class LaunchReleasePipelineRequest(BaseModel):
    repo:              str  = Field(..., min_length=3, max_length=200)
    base_sha:          str  = Field(..., min_length=7, max_length=40)
    render_service_id: str  = Field(..., min_length=3, max_length=100)
    base_branch:       str  = Field("main", max_length=100)
    health_url:        Optional[str] = Field(None, max_length=500)
    plan_notes:        Optional[str] = Field(None, max_length=5000)
    lint_workflow_id:  Optional[str] = None
    test_workflow_id:  Optional[str] = None
    security_workflow_id: Optional[str] = None
    build_workflow_id: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/missions", status_code=201)
async def create_mission(
    body: CreateMissionRequest,
    ctx: OrgContext = Depends(require_permission("engineering", "create")),
) -> dict[str, Any]:
    """Create a new Engineering Mission (status=PLANNED)."""
    from app.engineering.missions import get_mission_service
    svc = get_mission_service()
    mission = await svc.create_mission(
        org_id=ctx.org_id,
        created_by=ctx.user_id,
        objective=body.objective,
        template=body.template,
        project_id=body.project_id,
        budget_tokens=body.budget_tokens or 200_000,
        budget_steps=body.budget_steps  or 100,
    )
    return mission


@router.get("/missions")
async def list_missions(
    status:  Optional[str] = Query(None),
    limit:   int           = Query(20, ge=1, le=100),
    offset:  int           = Query(0, ge=0),
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """List missions for the current organization."""
    from app.engineering.missions import get_mission_service
    svc = get_mission_service()
    missions = await svc.list_missions(
        org_id=ctx.org_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"missions": missions, "count": len(missions)}


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """Get a single mission with its current state."""
    from app.engineering.missions import get_mission_service, MissionNotFound
    svc = get_mission_service()
    try:
        return await svc.get_mission(mission_id, org_id=ctx.org_id)
    except MissionNotFound:
        raise HTTPException(404, "mission not found")


@router.delete("/missions/{mission_id}", status_code=204)
async def cancel_mission(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "write")),
) -> None:
    """Cancel a running or queued mission."""
    from app.engineering.missions import get_mission_service, MissionNotFound
    svc = get_mission_service()
    try:
        await svc.transition(
            mission_id,
            org_id=ctx.org_id,
            to_status="CANCELLED",
            actor=ctx.user_id,
            reason="cancelled by user",
        )
    except MissionNotFound:
        raise HTTPException(404, "mission not found")
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.get("/missions/{mission_id}/tasks")
async def list_tasks(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """List all tasks for a mission."""
    from app.engineering.missions import get_mission_service, MissionNotFound
    svc = get_mission_service()
    try:
        tasks = await svc.list_tasks(mission_id, org_id=ctx.org_id)
        return {"tasks": tasks, "count": len(tasks)}
    except MissionNotFound:
        raise HTTPException(404, "mission not found")


@router.get("/missions/{mission_id}/transitions")
async def list_transitions(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """Return the FSM audit trail for a mission."""
    from app.engineering.missions import get_mission_service, MissionNotFound
    svc = get_mission_service()
    try:
        transitions = await svc.list_transitions(mission_id, org_id=ctx.org_id)
        return {"transitions": transitions}
    except MissionNotFound:
        raise HTTPException(404, "mission not found")


@router.post("/missions/{mission_id}/launch", status_code=202)
async def launch_release_pipeline(
    mission_id: str,
    body: LaunchReleasePipelineRequest,
    ctx: OrgContext = Depends(require_permission("engineering", "execute")),
) -> dict[str, Any]:
    """
    Enqueue a Release Autopilot job for this mission.

    org_id and user_id come from OrgContext — NOT from the request body.
    Returns the job_id; actual execution happens asynchronously.
    """
    from app.engineering.missions import get_mission_service, MissionNotFound
    from app.core.jobs.queue import get_job_queue

    svc = get_mission_service()
    try:
        mission = await svc.get_mission(mission_id, org_id=ctx.org_id)
    except MissionNotFound:
        raise HTTPException(404, "mission not found")

    if mission["status"] not in ("PLANNED", "FAILED", "RECOVERING"):
        raise HTTPException(
            400,
            f"cannot launch in status {mission['status']!r}; "
            "expected PLANNED, FAILED, or RECOVERING",
        )

    # Validate health_url if provided (SSRF guard)
    if body.health_url:
        try:
            from app.core.ssrf_guard import assert_public_url
            assert_public_url(body.health_url)
        except Exception as exc:
            raise HTTPException(400, f"invalid health_url: {exc}")

    # Transition to QUEUED
    await svc.transition(
        mission_id,
        org_id=ctx.org_id,
        to_status="QUEUED",
        actor=ctx.user_id,
        reason="launch_release_pipeline requested",
    )

    # Enqueue the job
    queue = get_job_queue()
    job_id = await queue.submit(
        "mission_run",
        payload={
            # org_id and user_id are injected server-side; never from body
            "org_id":               ctx.org_id,
            "user_id":              ctx.user_id,
            "user_role":            ctx.role,
            "mission_id":           mission_id,
            "repo":                 body.repo,
            "base_sha":             body.base_sha,
            "base_branch":          body.base_branch,
            "render_service_id":    body.render_service_id,
            "health_url":           body.health_url,
            "plan_notes":           body.plan_notes,
            "lint_workflow_id":     body.lint_workflow_id,
            "test_workflow_id":     body.test_workflow_id,
            "security_workflow_id": body.security_workflow_id,
            "build_workflow_id":    body.build_workflow_id,
        },
        org_id=ctx.org_id,
        idempotency_key=f"mission:{mission_id}:launch",
    )

    log.info(
        "launch_release_pipeline: mission=%s job=%s user=%s",
        mission_id[:8], job_id[:8], ctx.user_id[:8],
    )
    return {
        "status":     "queued",
        "mission_id": mission_id,
        "job_id":     job_id,
        "note":       "pipeline running asynchronously; poll GET /missions/{id}",
    }
