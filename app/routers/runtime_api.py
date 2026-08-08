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

SECURITY FIX: every per-execution route below (status/report/artifacts/
artifact download/cancel) previously relied solely on
api_auth_middleware's "/api/ requires *some* valid token" gate — the
in-memory `_executions` registry carried no ownership information at
all, so any authenticated user who learned or guessed an execution_id
(a uuid4()[:16], not a secret meant to gate access) could read another
user's execution status/report/artifacts, or cancel their still-running
execution outright (a cross-tenant sabotage/DoS vector, worse than a
read-only leak). `execute()` now stamps the verified caller's user id
into the record; every downstream route resolves the same
`_require_owned_execution()` guard and 404s (not 403 — a caller outside
the owner must not be able to tell "doesn't exist" apart from "exists,
isn't yours") before touching anything. cache/runtimes endpoints are
platform-wide, not per-execution data, and are unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.core.auth import owner_user_id
from app.core.db import get_pool
from app.core.filesystem import workspace as resolve_workspace
from app.core.helpers import resolve_project_id
from app.execution.platform import (
    ArtifactSystem,
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
    options   : dict = {}


# ── Execute (SSE stream) ──────────────────────────────────────────────────────

@router.post("/api/runtime/execute")
async def execute(req: ExecuteRequest, request: Request):
    """
    Start execution and stream TypedEvent objects as SSE.

    Every event is a JSON object with a `type` field.
    The final event is always `{"type": "report", "report": {...}}`.

    SECURITY FIX: this previously took a client-supplied `workspace`
    absolute path string and handed it straight to
    UnifiedExecutionEngine.run(), which copies that directory into a
    sandbox and runs install/build/launch against it
    (app/execution/platform/sandbox.py, engine.py). The route sits behind
    api_auth_middleware (any logged-in caller), but nothing tied the path
    to the caller's own project — any authenticated user could point the
    engine at another org's workspace or any directory readable by the
    server process: an arbitrary-file-read + arbitrary-code-execution
    primitive gated by nothing but a valid session. `workspace` is now
    removed from the request body entirely; the workspace is derived
    server-side from a verified project_id, matching the ownership check
    build.py's file endpoints already use (owner_user_id + resolve_project_id)
    and the path confinement app.core.filesystem.workspace() already
    enforces (WORKSPACES/-relative only, traversal-safe).
    """
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
        await resolve_project_id(conn, req.project_id, uid)

    ws = resolve_workspace(req.project_id)

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
                "owner_uid": str(uid),
            }

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Ownership guard ─────────────────────────────────────────────────────────

async def _require_owned_execution(execution_id: str, request: Request) -> dict:
    """404s (never 403) unless the verified caller is the same user who
    started this execution. A record with no `owner_uid` (shouldn't occur
    via execute() above, but is possible for hand-inserted test data) is
    treated as unowned/inaccessible rather than open to everyone."""
    rec = _executions.get(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="execution not found")
    async with get_pool().acquire() as conn:
        uid = await owner_user_id(conn, request)
    if rec.get("owner_uid") != str(uid):
        raise HTTPException(status_code=404, detail="execution not found")
    return rec


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/status")
async def get_status(execution_id: str, request: Request):
    rec = await _require_owned_execution(execution_id, request)
    return {"execution_id": execution_id, "status": rec.get("status", "unknown")}


# ── Report ────────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/report")
async def get_report(execution_id: str, request: Request):
    rec = await _require_owned_execution(execution_id, request)
    return rec.get("report", {})


# ── Artifacts ─────────────────────────────────────────────────────────────────

@router.get("/api/runtime/{execution_id}/artifacts")
async def list_artifacts(execution_id: str, request: Request):
    await _require_owned_execution(execution_id, request)
    arts = ArtifactSystem.load(execution_id)
    return {"artifacts": [a.to_dict() for a in arts.all()]}


@router.get("/api/runtime/{execution_id}/artifacts/{artifact_id}")
async def download_artifact(execution_id: str, artifact_id: str, request: Request):
    await _require_owned_execution(execution_id, request)
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
async def cancel_execution(execution_id: str, request: Request):
    await _require_owned_execution(execution_id, request)
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
