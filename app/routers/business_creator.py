"""Authenticated Business Creator API.

Execution is intentionally limited to app/store builds backed by the existing
SaaS Factory pipeline. Other types return 409 rather than fake success.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.business_creator import list_capabilities, plan_request
from app.saas_factory.pipeline import get_pipeline
from app.tenancy import OrgContext, require_permission

router = APIRouter(prefix="/api/business-creator", tags=["business-creator"])


class PlanRequest(BaseModel):
    capability: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=10, max_length=3000)


def _plan(body: PlanRequest) -> dict:
    try:
        return plan_request(body.capability, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/capabilities")
async def capabilities(
    _ctx: OrgContext = Depends(require_permission("saas_factory", "read")),
) -> dict:
    return {"capabilities": list_capabilities()}


@router.post("/plan")
async def plan(
    body: PlanRequest,
    _ctx: OrgContext = Depends(require_permission("saas_factory", "read")),
) -> dict:
    return _plan(body)


@router.post("/execute", status_code=202)
async def execute(
    body: PlanRequest,
    ctx: OrgContext = Depends(require_permission("saas_factory", "create")),
) -> dict:
    planned = _plan(body)
    if body.capability not in {"app", "store"}:
        raise HTTPException(
            status_code=409,
            detail="This capability has no verified execution adapter yet",
        )
    project_id = str(uuid.uuid4())
    await get_pipeline().start(
        project_id=project_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        idea_text=(
            f"Build an online store with a product catalog and storefront. {body.description}"
            if body.capability == "store"
            else body.description
        ),
    )
    return {
        "project_id": project_id,
        "status": "submitted",
        "engine": planned["engine"],
        "detail_url": f"/api/saas-factory/projects/{project_id}",
        "published": False,
    }
