"""
Usage & plans API — Layer 12 (billing foundation).

GET  /api/plans                              public plan catalog
GET  /api/orgs/{org_id}/usage                current-period usage summary
POST /api/orgs/{org_id}/usage/record         record usage (internal/admin)
PUT  /api/orgs/{org_id}/usage/limits/{metric} set per-org override (admin)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.billing import METRICS, PLANS, QuotaExceeded, get_usage_service
from app.tenancy import OrgContext, org_context, require_permission

router = APIRouter(tags=["usage"])


class RecordUsageRequest(BaseModel):
    metric: str
    amount: int = Field(default=1, ge=1, le=1_000_000_000)
    ref_type: str | None = None
    ref_id: str | None = None


class SetLimitRequest(BaseModel):
    limit: int = Field(ge=-1)


@router.get("/api/plans")
async def list_plans():
    return {"plans": [
        {"id": p.id, "name": p.name, "price_monthly_usd": p.price_monthly_usd,
         "limits": p.limits, "features": list(p.features), "trial_days": p.trial_days}
        for p in PLANS.values()
    ]}


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
    if metric not in METRICS:
        raise HTTPException(400, f"Unknown metric. Valid: {list(METRICS)}")
    svc = get_usage_service()
    await svc.set_override(ctx.org_id, metric, body.limit)
    return {"metric": metric, "limit": body.limit}
