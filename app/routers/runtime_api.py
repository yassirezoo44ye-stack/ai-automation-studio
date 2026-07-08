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
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.execution.platform import (
    ArtifactSystem,
    ExecutionReport,
    UnifiedExecutionEngine,
    get_cache,
    get_registry,
)
from app.execution.platform.artifacts import ArtifactSystem

log = logging.getLogger(__name__)
router = APIRouter(tags=["runtime"])

# In-memory execution registry (process-lifetime)
_executions: dict[str, dict] = {}   # execution_id → {"report": …, "artifacts": …, "status": …}


# ── Request/response models ────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    project_id: str = ""
    workspace : str = ""        # absolute path to the project workspace
    options   : dict = {}


# ── Execute (SSE stream) ──────────────────────────────────────────────────────

@router.post("/api/runtime/execute")
async def execute(req: ExecuteRequest):
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
async def get_status(execution_id: str):
    rec = _executions.get(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="execution not found")
    return {"execution_id": execution_id, "status": rec.get("status", "unknown")}


# ── Report ────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/report")
async def get_report(execution_id: str):
    rec = _executions.get(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="execution not found")
    return rec.get("report", {})


# ── Artifacts ─────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/artifacts")
async def list_artifacts(execution_id: str):
    arts = ArtifactSystem.load(execution_id)
    return {"artifacts": [a.to_dict() for a in arts.all()]}


@router.get("/api/runtime/{execution_id}/artifacts/{artifact_id}")
async def download_artifact(execution_id: str, artifact_id: str):
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
async def cancel_execution(execution_id: str):
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
