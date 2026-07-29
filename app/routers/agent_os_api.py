"""
Agentic OS REST API — full autonomous development platform.

Core execution:
  POST /api/agentos/run          Natural language → agent execution
  POST /api/agentos/collaborate  Multi-task pipeline
  POST /api/agentos/plan         Goal decomposition + execution
  POST /api/agentos/deliberate   Multi-agent voting + execution

Deliverables:
  GET  /api/agentos/deliverables/{id}  Download a file an agent produced

System state:
  GET  /api/agentos/status       Full system status
  GET  /api/agentos/agents       Agent list + per-agent stats
  GET  /api/agentos/memory       Execution history
  GET  /api/agentos/performance  Error rates + underperformers

Self-evolution:
  POST /api/agentos/evolve       Trigger evolution cycle
  GET  /api/agentos/reflections  Self-reflection history

Autonomous development:
  POST /api/agentos/generate     Write a new agent from description
  POST /api/agentos/suggest      Propose new features
  POST /api/agentos/implement    Implement a suggestion
  POST /api/agentos/loop         Run N autonomous improvement cycles

Monitoring:
  GET  /api/agentos/loop/stats   Background loop status
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.routers.auth_users import get_current_user

log    = logging.getLogger(__name__)
router = APIRouter(tags=["agentos"])


# ── Request models ────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    input      : str
    workspace  : Optional[str] = None
    project_id : Optional[str] = None
    caller     : str = "api"
    user_id    : Optional[str] = None
    deliberate : bool = False
    # Client-generated, so a "live computer" viewer can start listening for
    # this run's narrated steps (see app/agents/liveness.py's publish_step)
    # before firing this request — the id has to be known ahead of time,
    # since this call blocks until the agent finishes. Left unset by
    # callers that don't need live progress; one is generated for them.
    run_id     : Optional[str] = None


class CollaborateRequest(BaseModel):
    tasks    : list[str] = Field(..., min_length=1)
    parallel : bool      = False
    workspace: Optional[str] = None
    caller   : str = "api"
    run_id   : Optional[str] = None


class PlanRequest(BaseModel):
    goal     : str
    workspace: Optional[str] = None
    caller   : str = "api"
    run_id   : Optional[str] = None


class EvolveRequest(BaseModel):
    dry_run: bool = False


class GenerateRequest(BaseModel):
    description: str
    agent_name : Optional[str] = None


class SuggestRequest(BaseModel):
    n: int = Field(default=3, ge=1, le=10)


class ImplementRequest(BaseModel):
    index: int


class LoopRequest(BaseModel):
    cycles: int = Field(default=3, ge=1, le=10)


# ── Core execution ────────────────────────────────────────────────────────────

@router.post("/api/agentos/run")
async def agentos_run(req: RunRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    kernel = get_agent_kernel()
    result = await kernel.run(
        req.input,
        caller     = req.caller,
        user_id    = req.user_id,
        workspace  = req.workspace,
        project_id = req.project_id,
        deliberate = req.deliberate,
        organization_id = await optional_org_id(request),
        run_id     = req.run_id,
    )
    return result.to_dict()


@router.post("/api/agentos/collaborate")
async def agentos_collaborate(req: CollaborateRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    kernel  = get_agent_kernel()
    results = await kernel.collaborate(
        req.tasks,
        caller    = req.caller,
        workspace = req.workspace,
        parallel  = req.parallel,
        organization_id = await optional_org_id(request),
        run_id    = req.run_id,
    )
    return {
        "tasks"   : req.tasks,
        "results" : [r.to_dict() for r in results],
        "success" : all(r.success for r in results),
        "parallel": req.parallel,
    }


@router.post("/api/agentos/plan")
async def agentos_plan(req: PlanRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    return await get_agent_kernel().plan_and_run(
        req.goal, caller=req.caller, workspace=req.workspace,
        organization_id=await optional_org_id(request),
        run_id=req.run_id,
    )


@router.post("/api/agentos/deliberate")
async def agentos_deliberate(req: RunRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    kernel = get_agent_kernel()
    result, vote = await kernel.deliberate_and_run(
        req.input,
        caller    = req.caller,
        user_id   = req.user_id,
        workspace = req.workspace,
        organization_id = await optional_org_id(request),
        run_id    = req.run_id,
    )
    return {"result": result.to_dict(), "deliberation": vote}


# ── Deliverables ─────────────────────────────────────────────────────────────

@router.get("/api/agentos/deliverables/{deliverable_id}")
async def agentos_download_deliverable(
    deliverable_id: str, request: Request, user: dict = Depends(get_current_user),
):
    """
    Downloads a file an agent produced (e.g. DeployAgent's zip archive —
    see app/agents/deliverables.py). Requires login; if the deliverable
    was registered with an organization_id, the caller must be a verified
    member of that same org (resolved the same way every other org-scoped
    read in this router does) — otherwise this 404s exactly like a
    nonexistent id, so a caller can't distinguish "wrong org" from
    "doesn't exist".
    """
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.agents import deliverables
    from app.tenancy.context import optional_org_id

    d = deliverables.get(deliverable_id)
    if d is None:
        raise HTTPException(404, "Deliverable not found")

    if d["organization_id"]:
        org_id = await optional_org_id(request)
        if org_id != d["organization_id"]:
            raise HTTPException(404, "Deliverable not found")

    path = Path(d["path"])
    if not path.exists():
        raise HTTPException(404, "Deliverable file no longer exists")

    return FileResponse(
        str(path), filename=d["label"], media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{d["label"]}"'},
    )


# ── System state ──────────────────────────────────────────────────────────────

@router.get("/api/agentos/status")
async def agentos_status(request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    return get_agent_kernel().status(organization_id=await optional_org_id(request))


@router.get("/api/agentos/agents")
async def agentos_agents(request: Request):
    """Agent registry is a single, process-wide dict shared by every
    tenant's plugin-installed and self-generated agents — always scoped
    to the caller's own org (built-ins + its own agents), never every
    tenant's custom agents."""
    from app.agents.kernel import get_agent_kernel
    from app.agents.memory import get_memory
    from app.agents.liveness import snapshot as liveness_snapshot
    from app.tenancy.context import optional_org_id
    kernel = get_agent_kernel()
    memory = get_memory()
    org_id = await optional_org_id(request)
    running = liveness_snapshot()
    agents = []
    for ag in kernel.visible_agents(org_id):
        stats = memory.stats(ag.name)
        agents.append({
            **ag.to_dict(), "stats": stats.to_dict(),
            "live": running.get(ag.name, {"status": "idle"}),
        })
    return {"count": len(agents), "agents": agents}


@router.get("/api/agentos/memory")
async def agentos_memory(request: Request, n: int = 50):
    """Execution history is a single, process-wide log shared by every
    tenant — a record's input/args/error can contain confidential
    business content, so this always scopes to the caller's own verified
    org (or the no-org bucket if the caller isn't in one), never the
    cross-tenant view."""
    from app.agents.memory import get_memory
    from app.tenancy.context import optional_org_id
    org_id = await optional_org_id(request)
    records = get_memory().recent(min(n, 200), org_id=org_id)
    return {"count": len(records), "records": [r.to_dict() for r in reversed(records)]}


@router.get("/api/agentos/performance")
async def agentos_performance(request: Request):
    """Execution stats are keyed by agent name across a single,
    process-wide memory log — scoped to the caller's own org's
    executions, same contract as /api/agentos/memory."""
    from app.agents.memory import get_memory
    from app.tenancy.context import optional_org_id
    org_id       = await optional_org_id(request)
    memory       = get_memory()
    stats        = memory.global_stats(org_id=org_id)
    underperform = memory.underperformers(org_id=org_id)
    total        = memory.total_count(org_id=org_id)
    errors       = sum(s.fail_count for s in stats)
    return {
        "total_executions"      : total,
        "global_error_rate"     : round(errors / total, 3) if total else 0,
        "underperforming_agents": [s.name for s in underperform],
        "agent_stats"           : [s.to_dict() for s in stats],
        "evolution_candidates"  : len(underperform),
    }


# ── Self-evolution ────────────────────────────────────────────────────────────

@router.post("/api/agentos/evolve")
async def agentos_evolve(req: EvolveRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    kernel = get_agent_kernel()
    org_id = await optional_org_id(request)
    if req.dry_run:
        return kernel.evolution_analysis(org_id)
    return await kernel.evolve(organization_id=org_id)


@router.get("/api/agentos/reflections")
async def agentos_reflections(request: Request, n: int = 20):
    """Reflection insight text is computed from execution stats across
    every tenant (a system-wide self-improvement signal, not attributable
    to one org) — error_rate/execution_count stay aggregate, but
    flagged_agents can name another org's plugin-installed or
    self-generated agent, so it's filtered to what the caller can see."""
    from app.agents.kernel import get_agent_kernel
    from app.agents.reflection import get_reflector
    from app.tenancy.context import optional_org_id
    org_id  = await optional_org_id(request)
    visible = set(get_agent_kernel().visible_agent_names(org_id))
    reflections = get_reflector().to_dict_list()
    for r in reflections:
        r["flagged_agents"] = [a for a in r.get("flagged_agents", []) if a in visible]
    return {"reflections": reflections}


# ── Autonomous development ─────────────────────────────────────────────────────

@router.post("/api/agentos/generate")
async def agentos_generate(req: GenerateRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    return await get_agent_kernel().generate_agent(
        req.description, req.agent_name,
        organization_id=await optional_org_id(request),
    )


@router.post("/api/agentos/suggest")
async def agentos_suggest(req: SuggestRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    suggestions = await get_agent_kernel().suggest(
        req.n, organization_id=await optional_org_id(request),
    )
    return {"count": len(suggestions), "suggestions": suggestions}


@router.post("/api/agentos/implement")
async def agentos_implement(req: ImplementRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    return await get_agent_kernel().implement(
        req.index, organization_id=await optional_org_id(request),
    )


@router.post("/api/agentos/loop")
async def agentos_loop(req: LoopRequest, request: Request):
    from app.agents.kernel import get_agent_kernel
    from app.tenancy.context import optional_org_id
    results = await get_agent_kernel().autonomous_loop(
        req.cycles, organization_id=await optional_org_id(request),
    )
    return {"cycles": req.cycles, "results": results}


# ── Monitoring ────────────────────────────────────────────────────────────────

@router.get("/api/agentos/loop/stats")
async def agentos_loop_stats():
    from app.agents.kernel import get_agent_kernel
    return get_agent_kernel().loop_stats()
