"""
Usage & plans API — Layer 12 (billing foundation).

GET  /api/plans                              public plan catalog
POST /api/admin/plans/{plan_id}              edit a plan (platform-admin only)
GET  /api/orgs/{org_id}/usage                current-period usage summary
POST /api/orgs/{org_id}/usage/record         record usage (internal/admin)
PUT  /api/orgs/{org_id}/usage/limits/{metric} set per-org override (admin)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.billing import METRICS, QuotaExceeded, get_plan_service, get_usage_service
from app.core.api_keys import ApiKeyRecord, require_api_key
from app.tenancy import OrgContext, org_context, require_permission

router = APIRouter(tags=["usage"])


class RecordUsageRequest(BaseModel):
    metric: str
    amount: int = Field(default=1, ge=1, le=1_000_000_000)
    ref_type: str | None = None
    ref_id: str | None = None


class SetLimitRequest(BaseModel):
    limit: int = Field(ge=-1)
    project_id: str = ""
    workflow_id: str = ""
    agent_id: str = ""


class UpdatePlanRequest(BaseModel):
    name: Optional[str] = None
    price_monthly_usd: Optional[float] = Field(default=None, ge=0)
    limits: Optional[dict[str, int]] = None
    features: Optional[list[str]] = None
    trial_days: Optional[int] = Field(default=None, ge=0)
    max_agents: Optional[int] = Field(default=None, ge=-1)
    max_workflows: Optional[int] = Field(default=None, ge=-1)
    stripe_price_id: Optional[str] = None
    is_purchasable: Optional[bool] = None
    active: Optional[bool] = None


def _plan_out(p) -> dict:
    return {
        "id": p.id, "name": p.name, "price_monthly_usd": p.price_monthly_usd,
        "limits": p.limits, "features": list(p.features), "trial_days": p.trial_days,
        "max_agents": p.max_agents, "max_workflows": p.max_workflows,
        "is_purchasable": p.is_purchasable,
    }


@router.get("/api/plans")
async def list_plans():
    plans = await get_plan_service().list_plans()
    return {"plans": [_plan_out(p) for p in plans]}


@router.post("/api/admin/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: UpdatePlanRequest,
    key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"])),
):
    """Edit the global plan catalog without a deploy. Not org-scoped — gated
    by the existing cross-org admin API-key mechanism (require_api_key),
    not require_permission (which needs an OrgContext this action has none
    of)."""
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    try:
        plan = await get_plan_service().update_plan(plan_id, actor_id=None, **fields)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _plan_out(plan)


@router.get("/api/orgs/{org_id}/usage")
async def usage_summary(ctx: OrgContext = Depends(org_context)):
    svc = get_usage_service()
    return await svc.summary(ctx.org_id)


@router.post("/api/orgs/{org_id}/usage/record", status_code=201)
async def record_usage(
    body: RecordUsageRequest,
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    if body.metric not in METRICS:
        raise HTTPException(400, f"Unknown metric. Valid: {list(METRICS)}")
    svc = get_usage_service()
    try:
        await svc.check_quota(ctx.org_id, body.metric, body.amount)
    except QuotaExceeded as e:
        raise HTTPException(429, str(e))
    total = await svc.record(
        ctx.org_id, body.metric, body.amount,
        ref_type=body.ref_type, ref_id=body.ref_id,
    )
    return {"metric": body.metric, "period_total": total}


@router.put("/api/orgs/{org_id}/usage/limits/{metric}")
async def set_limit(
    metric: str,
    body: SetLimitRequest,
    ctx: OrgContext = Depends(require_permission("billing", "manage")),
):
    """Org-level limit by default; pass project_id/workflow_id/agent_id in
    the body for a finer-grained ceiling (AI Routing budget granularity —
    see app/billing/usage.py). A scoped limit is additional to, not a
    replacement for, the org-level one."""
    if metric not in METRICS:
        raise HTTPException(400, f"Unknown metric. Valid: {list(METRICS)}")
    svc = get_usage_service()
    await svc.set_override(
        ctx.org_id, metric, body.limit,
        project_id=body.project_id, workflow_id=body.workflow_id, agent_id=body.agent_id,
    )
    try:
        from app.tenancy import get_tenancy_service
        await get_tenancy_service().log_activity(
            ctx.org_id, ctx.user_id, "usage.limit_overridden",
            resource="usage_limit", resource_id=metric,
            details={
                "metric": metric, "limit": body.limit,
                "project_id": body.project_id or None,
                "workflow_id": body.workflow_id or None,
                "agent_id": body.agent_id or None,
            },
        )
    except Exception:
        pass
    return {
        "metric": metric, "limit": body.limit,
        "scope": {
            "project_id":  body.project_id or None,
            "workflow_id": body.workflow_id or None,
            "agent_id":    body.agent_id or None,
        },
    }
