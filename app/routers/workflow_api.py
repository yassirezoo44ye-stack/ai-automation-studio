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

Tenant boundary (P0.5 security sweep, see
docs/security-tenant-boundary-sweep.md — closes the "known residual gap"
this file used to document here): every route now requires org_context
and passes ctx.org_id into WorkflowEngine's active()/pending_approvals()/
approve()/reject(), which filter/verify against each WorkflowRun's own
context["organization_id"] (set server-side by whoever built the run —
see WorkflowBuilder.build(context=...) and app/routers/orchestrator.py's
run_workflow(), never a client-supplied field). A run with no
organization_id on record is only visible to callers with no org context
of their own — never treated as "everyone's". approve_step/reject_step
404 (not 403) on a run that doesn't exist or isn't the caller's, same
convention as app/routers/jobs_api.py.
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
    return {"runs": engine.active(organization_id=ctx.org_id)}


@router.get("/approvals/pending")
def list_pending_approvals(ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    return {"pending": engine.pending_approvals(organization_id=ctx.org_id)}


@router.post("/approvals/{run_id}/{step_id}/approve")
def approve_step(run_id: str, step_id: str, ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    if not engine.approve(run_id, step_id, organization_id=ctx.org_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return {"approved": True, "run_id": run_id, "step_id": step_id}


@router.post("/approvals/{run_id}/{step_id}/reject")
def reject_step(run_id: str, step_id: str, ctx: OrgContext = Depends(org_context)):
    engine = get_workflow_engine()
    if not engine.reject(run_id, step_id, organization_id=ctx.org_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
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
