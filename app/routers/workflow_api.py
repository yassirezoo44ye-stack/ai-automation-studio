"""
Workflow Engine REST API — Layer 8 surface.

GET  /workflows/active               list currently running workflow runs
GET  /workflows/approvals/pending    list steps waiting for human approval
POST /workflows/approvals/{run_id}/{step_id}/approve  approve a step
POST /workflows/approvals/{run_id}/{step_id}/reject   reject a step
POST /workflows/demo                 run a demo 3-step workflow
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.workflow import (
    WorkflowBuilder, RetryPolicy, get_workflow_engine,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


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
