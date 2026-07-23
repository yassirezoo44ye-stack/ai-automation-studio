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

KNOWN RESIDUAL GAP (flagged, not fixed here): the /api/ prefix now
requires a real authenticated caller, but WorkflowRun/the approval
registry (app/core/workflow/engine.py's WorkflowEngine._active +
_approval_registry) carry no organization_id at all — active()/
pending_approvals() return every org's runs, and approve()/reject()
never verify the run belongs to the caller's org. Any authenticated user
from ANY org can approve/reject/inspect another org's workflow step
today. Closing this needs WorkflowRun to carry organization_id from
WorkflowBuilder.build(context=...) through to the approval registry — a
larger change than the auth fix above, tracked separately rather than
folded into this commit.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.core.workflow import (
    WorkflowBuilder, RetryPolicy, get_workflow_engine,
)

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
def list_active():
    engine = get_workflow_engine()
    return {"runs": engine.active()}


@router.get("/approvals/pending")
def list_pending_approvals():
    engine = get_workflow_engine()
    return {"pending": engine.pending_approvals()}


@router.post("/approvals/{run_id}/{step_id}/approve")
def approve_step(run_id: str, step_id: str):
    engine = get_workflow_engine()
    engine.approve(run_id, step_id)
    return {"approved": True, "run_id": run_id, "step_id": step_id}


@router.post("/approvals/{run_id}/{step_id}/reject")
def reject_step(run_id: str, step_id: str):
    engine = get_workflow_engine()
    engine.reject(run_id, step_id)
    return {"rejected": True, "run_id": run_id, "step_id": step_id}


@router.post("/demo")
async def run_demo_workflow():
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
        .build(context={"source": "demo"})
    )
    result = await engine.execute(run, saga=True)
    return result.to_dict()
