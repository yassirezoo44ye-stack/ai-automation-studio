"""
Public Runtime API — Phase 14 of the Execution Platform.

Endpoints:

  POST   /api/runtime/execute          — start execution, SSE stream
  GET    /api/runtime/{id}/status      — execution status
  GET    /api/runtime/{id}/report      — full execution report
  GET    /api/runtime/{id}/artifacts   — list artifacts
  GET    /api/runtime/{id}/artifacts/{artifact_id} — download artifact
  DELETE /api/runtime/{id}             — cancel / cleanup execution
  GET    /api/runtime/cache/stats      — cache statistics
  DELETE /api/runtime/cache            — evict expired cache entries
  GET    /api/runtime/runtimes         — list registered runtimes

Tenant boundary (P0.5 security fix, see docs/security-tenant-boundary-audit.md):
execute() records the caller's verified org_id (org_context, never a
client-supplied value) alongside each execution; every id-based lookup
below re-verifies the caller's org_id matches before returning anything,
404ing otherwise so a non-member can't distinguish "wrong org" from
"doesn't exist" — same convention as app/routers/jobs_api.py. cache/stats,
cache/evict and runtimes carry no tenant data and are intentionally left
unscoped.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.execution.platform import (
    ArtifactSystem,
    UnifiedExecutionEngine,
    get_cache,
    get_registry,
)
from app.execution.platform.artifacts import ArtifactSystem
from app.tenancy.context import OrgContext, org_context

log = logging.getLogger(__name__)
router = APIRouter(tags=["runtime"])

# In-memory execution registry (process-lifetime)
_executions: dict[str, dict] = {}   # execution_id → {"org_id": …, "report": …, "status": …}


def _owned_execution(execution_id: str, ctx: OrgContext) -> dict:
    """Look up an execution and verify it belongs to the caller's org.
    404 either way (not 403) — a caller outside this org must not be able
    to tell "doesn't exist" apart from "exists, isn't yours"."""
    rec = _executions.get(execution_id)
    if not rec or rec.get("org_id") != ctx.org_id:
        raise HTTPException(status_code=404, detail="execution not found")
    return rec


# ── Request/response models ────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    project_id: str = ""
    workspace : str = ""        # absolute path to the project workspace
    options   : dict = {}


# ── Execute (SSE stream) ──────────────────────────────────────────────────────

@router.post("/api/runtime/execute")
async def execute(req: ExecuteRequest, ctx: OrgContext = Depends(org_context)):
    """
    Start execution and stream TypedEvent objects as SSE.

    Every event is a JSON object with a `type` field.
    The final event is always `{"type": "report", "report": {...}}`.
    """
    ws = Path(req.workspace) if req.workspace else None

    if ws is None or not ws.exists():
        raise HTTPException(status_code=400, detail=f"workspace does not exist: {req.workspace}")

    engine       = UnifiedExecutionEngine()
    execution_id = None
    org_id       = ctx.org_id

    async def _stream() -> AsyncIterator[str]:
        nonlocal execution_id
        report    = None
        artifacts = None

        async for event in engine.run(ws, project_id=req.project_id, options=req.options):
            d = event.to_sse_dict()

            if execution_id is None:
                execution_id = d.get("execution_id", "")

            if d.get("type") == "report":
                report = d.get("report", {})

            yield f"data: {json.dumps(d)}\n\n"

        # Register the completed execution for status/report/artifact queries
        if execution_id:
            _executions[execution_id] = {
                "status"  : "done",
                "report"  : report or {},
                "workspace": str(ws),
                "org_id"  : org_id,
            }

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/status")
async def get_status(execution_id: str, ctx: OrgContext = Depends(org_context)):
    rec = _owned_execution(execution_id, ctx)
    return {"execution_id": execution_id, "status": rec.get("status", "unknown")}


# ── Report ────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/report")
async def get_report(execution_id: str, ctx: OrgContext = Depends(org_context)):
    rec = _owned_execution(execution_id, ctx)
    return rec.get("report", {})


# ── Artifacts ─────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/artifacts")
async def list_artifacts(execution_id: str, ctx: OrgContext = Depends(org_context)):
    _owned_execution(execution_id, ctx)
    arts = ArtifactSystem.load(execution_id)
    return {"artifacts": [a.to_dict() for a in arts.all()]}


@router.get("/api/runtime/{execution_id}/artifacts/{artifact_id}")
async def download_artifact(execution_id: str, artifact_id: str, ctx: OrgContext = Depends(org_context)):
    _owned_execution(execution_id, ctx)
    arts = ArtifactSystem.load(execution_id)
    art  = arts.get(artifact_id)
    if not art or not art.exists:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(
        path        = art.path,
        filename    = art.name,
        media_type  = art.mime_type,
    )


# ── Cancel / cleanup ──────────────────────────────────────────────────────────

@router.delete("/api/runtime/{execution_id}")
async def cancel_execution(execution_id: str, ctx: OrgContext = Depends(org_context)):
    _owned_execution(execution_id, ctx)
    try:
        from app.execution.process_mgr import kill_execution
        kill_execution(execution_id)
    except Exception:
        pass
    _executions.pop(execution_id, None)
    return {"cancelled": execution_id}


# ── Cache ─────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/cache/stats")
async def cache_stats():
    return get_cache().stats()


@router.delete("/api/runtime/cache")
async def evict_cache():
    evicted = get_cache().evict_expired()
    return {"evicted": evicted}


# ── Runtime list ──────────────────────────────────────────────────────────────

@router.get("/api/runtime/runtimes")
async def list_runtimes():
    runtimes = [
        {"name": rt.name, "priority": rt.priority}
        for rt in get_registry().all()
    ]
    return {"runtimes": runtimes}
