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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import owner_user_id
from app.core.db import get_pool
from app.core.helpers import resolve_project_id
from app.core.project_plans import plan_organization

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["planning"])

_plan_cache: dict[tuple[str, str | None, str], dict] = {}   # plan_id → serialised plan


class PlanRequest(BaseModel):
    goal      : str = Field(min_length=3, max_length=4000)
    caller    : str = "api"
    project_id: str | None = None
    execute   : bool = False          # if True, run the plan after building it


@router.post("/analyze")
async def plan_analyze(req: PlanRequest, request: Request):
    """Build and return a plan without executing it."""
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    uid, org = await _scope(request, req.project_id)
    kernel  = get_agent_kernel()
    engine  = get_planning_engine()
    plan    = engine.plan(req.goal, caller=req.caller, agents={a.name: a for a in kernel.visible_agents(org)})
    serialised = plan.to_dict()
    _remember(uid, org, plan.plan_id, serialised)
    return serialised


@router.post("/execute")
async def plan_execute(req: PlanRequest, request: Request):
    """Build a plan and execute it through the AgentKernel."""
    from app.planning.engine    import get_planning_engine
    from app.agents.kernel      import get_agent_kernel

    uid, org = await _scope(request, req.project_id)

    kernel = get_agent_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(req.goal, caller=req.caller, agents={a.name: a for a in kernel.visible_agents(org)})
    serialised = plan.to_dict()
    _remember(uid, org, plan.plan_id, serialised)

    issues = engine.validate_plan(plan)
    by_id = {task.id: task for task in plan.tasks}
    ordered = [task_id for group in plan.parallel_groups for task_id in group]
    if len(ordered) != len(by_id) or set(ordered) != set(by_id):
        issues.append("Invalid execution schedule")
    resolved = set()
    for group in plan.parallel_groups:
        if any(task_id not in by_id or not set(by_id[task_id].depends_on) <= resolved for task_id in group):
            issues.append("Unresolved task dependencies")
        resolved.update(group)
    if not plan.is_safe or plan.requires_approval or issues:
        return {
            "plan"    : serialised,
            "executed": False,
            "reason"  : "Plan requires approval or has permission/risk errors",
            "issues"  : issues,
        }

    # Execute the validated graph, never ask a second planner to invent new steps.
    results = []
    commands = []
    for group in plan.parallel_groups:
        for task_id in group:
            task = by_id[task_id]
            if not task.agent_name:
                raise HTTPException(409, "Plan task has no assigned agent")
            result = await kernel.run(
                task.description, caller=req.caller, user_id=str(uid),
                project_id=req.project_id, organization_id=org, forced_intent=task.agent_name,
            )
            results.append(result.to_dict())
            commands.append(f"{task.agent_name} {task.description}")
            if not result.success:
                break
        if results and not results[-1]["success"]:
            break
    execution = {"goal": req.goal, "plan": commands, "results": results,
                 "success": bool(results) and all(r["success"] for r in results), "method": "validated_plan"}
    return {
        "plan"     : serialised,
        "execution": execution,
        "executed" : True,
    }


@router.get("/{plan_id}")
async def get_plan(plan_id: str, request: Request):
    uid, org = await _scope(request)
    plan = _plan_cache.get((str(uid), org, plan_id))
    if not plan:
        raise HTTPException(404, f"Plan {plan_id!r} not found")
    return plan


@router.post("/validate")
async def plan_validate(req: PlanRequest, request: Request):
    """
    Build a plan and run the validator (stages 8–10) without executing.
    Returns the plan + any blocking issues + schedule + capability map.
    """
    from app.planning.engine import get_planning_engine
    from app.agents.kernel   import get_agent_kernel

    uid, org = await _scope(request, req.project_id)
    kernel = get_agent_kernel()
    engine = get_planning_engine()
    plan   = engine.plan(req.goal, caller=req.caller, agents={a.name: a for a in kernel.visible_agents(org)})

    issues        = engine.validate_plan(plan)
    capabilities  = engine.match_capabilities(plan.tasks, {a.name: a for a in kernel.visible_agents(org)})
    sched         = engine.schedule(plan.tasks, plan.parallel_groups)

    return {
        "plan"        : plan.to_dict(),
        "issues"      : issues,
        "safe"        : len(issues) == 0,
        "capabilities": capabilities,
        "schedule"    : sched,
    }


async def _scope(request, project_id=None):
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        if project_id:
            await resolve_project_id(conn, project_id, uid)
    org = await plan_organization(request)
    return uid, str(org) if org else None


def _remember(uid, org, plan_id, value):
    if len(_plan_cache) >= 256:
        _plan_cache.pop(next(iter(_plan_cache)))
    _plan_cache[(str(uid), org, plan_id)] = value
