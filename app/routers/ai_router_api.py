"""
AI Cost Router API — Layer 6 (AI Gateway).

GET  /api/ai/models              catalog with pricing/quality/speed
POST /api/ai/route               get a routing decision for a request profile
GET  /api/ai/route/decisions     recent routing decisions
GET  /api/orgs/{org_id}/ai/costs per-org cost breakdown
GET  /api/ai/providers           provider health + circuit breaker state
GET  /api/ai/budgets             org/project/workflow/agent budget status
GET  /api/ai/usage               total spend from ai_usage_log (org-scoped
                                  when X-Organization-Id is present)
GET  /api/ai/usage/providers     spend broken down by provider
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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


# ── Provider health ───────────────────────────────────────────────────────────

@router.get("/api/ai/providers")
async def provider_health():
    """Platform-wide — not org-scoped: which providers are configured, and
    each one's circuit breaker state (see app/ai/circuit_breaker.py)."""
    from app.core.ai.registry.registry import platform_registry
    return {"providers": platform_registry.health()}


# ── Budgets ───────────────────────────────────────────────────────────────────

@router.get("/api/ai/budgets")
async def budgets(
    ctx: OrgContext = Depends(org_context),
    project_id: str = "",
    workflow_id: str = "",
    agent_id: str = "",
):
    """Usage vs. limit for every metric at the given scope. Omit
    project_id/workflow_id/agent_id for the organization's own budget;
    pass one to see that finer-grained ceiling (see app/billing/usage.py)."""
    from app.billing import get_usage_service
    from app.billing.plans import METRICS

    svc   = get_usage_service()
    usage = await svc.get_usage(ctx.org_id, project_id=project_id,
                                workflow_id=workflow_id, agent_id=agent_id)
    metrics: dict[str, dict] = {}
    for metric in METRICS:
        limit = await svc.get_limit(ctx.org_id, metric, project_id=project_id,
                                    workflow_id=workflow_id, agent_id=agent_id)
        used = usage.get(metric, 0)
        metrics[metric] = {
            "used":  used,
            "limit": limit,
            "pct":   None if limit <= 0 else round(min(used / limit, 1.0) * 100, 1),
        }
    return {
        "organization_id": ctx.org_id,
        "scope": {
            "project_id":  project_id or None,
            "workflow_id": workflow_id or None,
            "agent_id":    agent_id or None,
        },
        "metrics": metrics,
    }


# ── Usage / cost reporting ───────────────────────────────────────────────────

def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since)
    except ValueError:
        raise HTTPException(400, f"Invalid 'since' timestamp: {since!r} (expected ISO 8601)")


@router.get("/api/ai/usage")
async def usage_summary(request: Request, since: Optional[str] = None):
    """Total spend from ai_usage_log — the consolidated cost ledger.
    Org-scoped when X-Organization-Id is present, platform-wide otherwise
    (mirrors app.core.org_quota's optional-org convention)."""
    from app.ai import cost_tracker
    from app.core.db import get_pool

    org_id  = getattr(request.state, "org_id", None)
    since_dt = _parse_since(since)
    totals  = await cost_tracker.totals(pool=get_pool(), org_id=org_id, since=since_dt)
    rows    = await cost_tracker.by_provider(pool=get_pool(), org_id=org_id, since=since_dt)

    by_provider: dict[str, float] = {}
    for row in rows:
        pid = row.get("provider", "unknown")
        by_provider[pid] = by_provider.get(pid, 0.0) + float(row.get("cost_usd") or 0)

    return {
        "total_usd": round(float(totals.get("cost_usd") or 0), 6),
        "by_provider": [
            {"provider_id": pid, "total_usd": round(usd, 6)}
            for pid, usd in by_provider.items()
        ],
    }


@router.get("/api/ai/usage/providers")
async def usage_by_provider(request: Request, since: Optional[str] = None):
    from app.ai import cost_tracker
    from app.core.db import get_pool

    org_id  = getattr(request.state, "org_id", None)
    since_dt = _parse_since(since)
    rows    = await cost_tracker.by_provider(pool=get_pool(), org_id=org_id, since=since_dt)

    by_provider: dict[str, float] = {}
    for row in rows:
        pid = row.get("provider", "unknown")
        by_provider[pid] = by_provider.get(pid, 0.0) + float(row.get("cost_usd") or 0)

    return {
        "providers": [
            {"provider_id": pid, "total_usd": round(usd, 6)}
            for pid, usd in by_provider.items()
        ],
    }
