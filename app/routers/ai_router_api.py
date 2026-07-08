"""
AI Cost Router API — Layer 6 (AI Gateway).

GET  /api/ai/models              catalog with pricing/quality/speed
POST /api/ai/route               get a routing decision for a request profile
GET  /api/ai/route/decisions     recent routing decisions
GET  /api/orgs/{org_id}/ai/costs per-org cost breakdown
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ai.cost_router import Policy, RouteRequest, get_cost_router
from app.tenancy import OrgContext, org_context

router = APIRouter(tags=["ai-routing"])


class RouteBody(BaseModel):
    est_input_tokens: int = Field(default=1000, ge=1, le=10_000_000)
    est_output_tokens: int = Field(default=1000, ge=1, le=10_000_000)
    min_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    max_cost_usd: float | None = Field(default=None, ge=0.0)
    required_context: int = Field(default=0, ge=0)
    exclude_providers: list[str] = []
    policy: str = Field(default="balanced",
                        pattern="^(cheapest|fastest|quality|balanced|custom)$")
    custom_weights: dict[str, float] = {}


@router.get("/api/ai/models")
async def list_models():
    return {"models": get_cost_router().list_models()}


@router.post("/api/ai/route")
async def route(body: RouteBody):
    try:
        decision = get_cost_router().route(RouteRequest(
            est_input_tokens=body.est_input_tokens,
            est_output_tokens=body.est_output_tokens,
            min_quality=body.min_quality,
            max_cost_usd=body.max_cost_usd,
            required_context=body.required_context,
            exclude_providers=tuple(body.exclude_providers),
            policy=Policy(body.policy),
            custom_weights=body.custom_weights,
        ))
    except LookupError as e:
        raise HTTPException(422, str(e))
    return decision


@router.get("/api/ai/route/decisions")
async def decisions(limit: int = 50):
    return {"decisions": get_cost_router().recent_decisions(limit)}


@router.get("/api/orgs/{org_id}/ai/costs")
async def org_costs(ctx: OrgContext = Depends(org_context)):
    return get_cost_router().costs_for_org(ctx.org_id)
