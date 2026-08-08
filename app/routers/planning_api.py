"""
Planning API — expose the PlanningEngine over REST.

POST /api/plan/analyze     Analyze goal + return plan (no execution)
POST /api/plan/execute     Analyze + execute with AgentKernel
GET  /api/plan/{plan_id}  Retrieve a cached plan by ID

SECURITY FIX: /execute previously had no caller-identity resolution at
all and passed a raw client-supplied `workspace` path straight through to
AgentKernel.plan_and_run() — which, for any plan step that resolves to
the "run" agent, ends up handed to UnifiedExecutionEngine (copies the
path into a sandbox, runs install/build/launch against it): an
arbitrary-file-read + arbitrary-code-execution primitive gated by nothing
but a valid session, same bug class as runtime_api.py's POST
/api/runtime/execute. The caller's identity is now resolved from the
verified auth token (never the request body — same as
agent_os_api.py's optional_user_id usage), and `workspace` is no longer
accepted from the client; run_agent.py itself re-derives the workspace
from a verified project_id.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["planning"])

_plan_cache: dict[str, dict] = {}   # plan_id → serialised plan


class PlanRequest(BaseModel):
    goal      : str
    caller    : str = "api"
    project_id: Optional[str] = None
    execute   : bool = False          # if True, run the plan after building it


@router.post("/analyze")
async def plan_analyze(req: PlanRequest):
    """Build and return a plan without executing it."""
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    kernel  = get_agent_kernel()
    engine  = get_planning_engine()
    plan    = engine.plan(req.goal, caller=req.caller, agents=kernel._agents)
    serialised = plan.to_dict()
    _plan_cache[plan.plan_id] = serialised
    return serialised


@router.post("/execute")
async def plan_execute(req: PlanRequest, request: Request):
    """Build a plan and execute it through the AgentKernel."""
    from app.core.auth import owner_user_id
    from app.core.db import get_pool
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)

    kernel = get_agent_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(req.goal, caller=req.caller, agents=kernel._agents)
    serialised = plan.to_dict()
    _plan_cache[plan.plan_id] = serialised

    if not plan.is_safe:
        return {
            "plan"    : serialised,
            "executed": False,
            "reason"  : "Plan has permission errors or CRITICAL risk — approve manually",
        }

    # Execute via kernel — identity resolved from the verified auth token
    # above, never the request body; any step that needs a workspace (e.g.
    # the "run" agent) re-derives it from req.project_id itself.
    execution = await kernel.plan_and_run(
        req.goal, caller=req.caller, user_id=str(uid), project_id=req.project_id,
    )
    return {
        "plan"     : serialised,
        "execution": execution,
        "executed" : True,
    }


@router.get("/{plan_id}")
async def get_plan(plan_id: str):
    plan = _plan_cache.get(plan_id)
    if not plan:
        raise HTTPException(404, f"Plan {plan_id!r} not found")
    return plan


@router.post("/validate")
async def plan_validate(req: PlanRequest):
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
