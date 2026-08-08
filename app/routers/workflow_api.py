"""
Workflow Engine REST API — Layer 8 surface.

GET  /api/workflows/active               list currently running workflow runs
GET  /api/workflows/approvals/pending    list steps waiting for human approval
POST /api/workflows/approvals/{run_id}/{step_id}/approve  approve a step
POST /api/workflows/approvals/{run_id}/{step_id}/reject   reject a step
POST /api/workflows/demo                 run a demo 3-step workflow

Was mounted at /workflows (no /api/ prefix) — app.factory's
api_auth_middleware only gates paths starting with /api/, so every
endpoint here, including approve/reject (a human-approval gate meant to
require a real, authorized person) was reachable with zero authentication
by anyone. Same shape of bug as the earlier chat.py /run(/stream) and
arabic_api.py fixes this phase.

SECURITY FIX: the /api/ prefix alone still left every org's runs/
approvals visible to any authenticated user from any other org —
WorkflowEngine.active() and pending_approvals() returned every org's data
unfiltered, and approve()/reject() never checked which org a run belonged
to before mutating it. Every endpoint here now requires org_context (real,
verified org membership, same as jobs_api.py), and every call into
WorkflowEngine passes ctx.org_id through — see engine.py's _owns_run/
_UNSCOPED. /demo stamps the caller's org_id into the run's context so its
own runs are visible under the new scoping.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.core.workflow import (
    WorkflowBuilder, RetryPolicy, get_workflow_engine,
)
from app.tenancy.context import OrgContext, org_context

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


# ── Demo step functions ───────────────────────────────────────────────────────

async def _step_validate(_context, _run_id, **_):
    await asyncio.sleep(0.05)
    return {"validated": True, "items": 42}


async def _step_process(_context, _run_id, **_):
    await asyncio.sleep(0.1)
    items = _context.get("validate.items", 0)
    return {"processed": items, "success": True}


async def _step_notify(_context, _run_id, **_):
    await asyncio.sleep(0.02)
    return {"notification": "sent", "channel": "slack"}


async def _step_rollback_process(_context, _run_id, **_):
    return {"rolled_back": "process"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/active")
def list_active(ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    return {"runs": engine.active(org_id=ctx.org_id)}


@router.get("/approvals/pending")
def list_pending_approvals(ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    return {"pending": engine.pending_approvals(org_id=ctx.org_id)}


@router.post("/approvals/{run_id}/{step_id}/approve")
def approve_step(run_id: str, step_id: str, ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    # 404 either way (not 403) — a caller outside this org must not be
    # able to tell "doesn't exist" apart from "exists, isn't yours".
    if not engine.approve(run_id, step_id, org_id=ctx.org_id):
        raise HTTPException(404, f"Workflow run {run_id!r} not found")
    return {"approved": True, "run_id": run_id, "step_id": step_id}


@router.post("/approvals/{run_id}/{step_id}/reject")
def reject_step(run_id: str, step_id: str, ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    if not engine.reject(run_id, step_id, org_id=ctx.org_id):
        raise HTTPException(404, f"Workflow run {run_id!r} not found")
    return {"rejected": True, "run_id": run_id, "step_id": step_id}


@router.post("/demo")
async def run_demo_workflow(ctx: OrgContext = Depends(org_context)):
    """
    Execute a 3-step demo workflow (validate → process → notify).
    Step 'process' has a Saga compensation function.
    Returns the full WorkflowRun result.
    """
    engine = get_workflow_engine()
    run = (
        WorkflowBuilder("demo-workflow")
        .step("validate", "Validate input", _step_validate,
              retry=RetryPolicy(max_attempts=2), timeout_s=5)
        .step("process", "Process items", _step_process,
              depends_on=["validate"],
              retry=RetryPolicy(max_attempts=3, base_delay_s=0.5),
              compensation=_step_rollback_process,
              timeout_s=10)
        .step("notify", "Send notification", _step_notify,
              depends_on=["process"], timeout_s=5)
        .build(context={"source": "demo", "organization_id": ctx.org_id})
    )
    result = await engine.execute(run, saga=True)
    return result.to_dict()
