"""
Planning API — expose the PlanningEngine over REST.

POST /api/plan/analyze     Analyze goal + return plan (no execution)
POST /api/plan/execute     Analyze + execute with AgentKernel
GET  /api/plan/{plan_id}  Retrieve a cached plan by ID

Tenant boundary (P0.5 security fix, see docs/security-tenant-boundary-audit.md):
_plan_cache is process-wide and plan_id carries no org info of its own, so
every entry is now stored keyed to the caller's verified org_id (org_context)
and get_plan() re-checks it before returning anything — 404 either way (not
403) so a non-member can't tell "wrong org" from "doesn't exist", matching
app/routers/jobs_api.py's convention. plan_execute() also now forwards
ctx.org_id into AgentKernel.plan_and_run()'s existing organization_id
parameter, which was previously always left as None.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.tenancy.context import OrgContext, org_context

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["planning"])

_plan_cache: dict[str, dict] = {}   # plan_id → {"org_id": …, "plan": serialised}


class PlanRequest(BaseModel):
    goal     : str
    caller   : str = "api"
    workspace: Optional[str] = None
    execute  : bool = False          # if True, run the plan after building it


@router.post("/analyze")
async def plan_analyze(req: PlanRequest, ctx: OrgContext = Depends(org_context)):
    """Build and return a plan without executing it."""
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    kernel  = get_agent_kernel()
    engine  = get_planning_engine()
    plan    = engine.plan(req.goal, caller=req.caller, agents=kernel._agents)
    serialised = plan.to_dict()
    _plan_cache[plan.plan_id] = {"org_id": ctx.org_id, "plan": serialised}
    return serialised


@router.post("/execute")
async def plan_execute(req: PlanRequest, ctx: OrgContext = Depends(org_context)):
    """Build a plan and execute it through the AgentKernel."""
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    kernel = get_agent_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(req.goal, caller=req.caller, agents=kernel._agents)
    serialised = plan.to_dict()
    _plan_cache[plan.plan_id] = {"org_id": ctx.org_id, "plan": serialised}

    if not plan.is_safe:
        return {
            "plan"    : serialised,
            "executed": False,
            "reason"  : "Plan has permission errors or CRITICAL risk — approve manually",
        }

    # Execute via kernel
    execution = await kernel.plan_and_run(
        req.goal, caller=req.caller, workspace=req.workspace,
        organization_id=ctx.org_id,
    )
    return {
        "plan"     : serialised,
        "execution": execution,
        "executed" : True,
    }


@router.get("/{plan_id}")
async def get_plan(plan_id: str, ctx: OrgContext = Depends(org_context)):
    entry = _plan_cache.get(plan_id)
    # 404 either way (not 403) — a caller outside this org must not be able
    # to tell "doesn't exist" apart from "exists, isn't yours".
    if not entry or entry.get("org_id") != ctx.org_id:
        raise HTTPException(404, f"Plan {plan_id!r} not found")
    return entry["plan"]


@router.post("/validate")
async def plan_validate(req: PlanRequest, ctx: OrgContext = Depends(org_context)):
    """
    Build a plan and run the validator (stages 8–10) without executing.
    Returns the plan + any blocking issues + schedule + capability map.
    """
    from app.planning.engine import get_planning_engine
    from app.agents.kernel   import get_agent_kernel

    kernel = get_agent_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(req.goal, caller=req.caller, agents=kernel._agents)

    issues        = engine.validate_plan(plan)
    capabilities  = engine.match_capabilities(plan.tasks, kernel._agents)
    sched         = engine.schedule(plan.tasks, plan.parallel_groups)

    return {
        "plan"        : plan.to_dict(),
        "issues"      : issues,
        "safe"        : len(issues) == 0,
        "capabilities": capabilities,
        "schedule"    : sched,
    }
