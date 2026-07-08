"""
Diagnostics API — detailed system introspection.

GET /api/diagnostics/health        Full health probe report
GET /api/diagnostics/metrics       Metrics snapshot (JSON)
GET /api/diagnostics/metrics/text  Prometheus text format
GET /api/diagnostics/traces        Recent distributed traces
GET /api/diagnostics/traces/active Active (in-flight) spans
GET /api/diagnostics/traces/{trace_id}  All spans for a trace
GET /api/diagnostics/services      Background service status
POST /api/diagnostics/services/{name}/start   Start a service
POST /api/diagnostics/services/{name}/stop    Stop a service
GET /api/diagnostics/memory        Layered memory stats
POST /api/diagnostics/memory/search  Semantic memory search
GET /api/diagnostics/codegen       Pending code-gen approvals
POST /api/diagnostics/codegen/{run_id}/approve
POST /api/diagnostics/codegen/{run_id}/reject
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def diagnostics_health():
    from app.core.observability.health import get_health_registry
    return await get_health_registry().check_all()


# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def diagnostics_metrics():
    from app.core.observability.metrics import get_metrics
    return get_metrics().snapshot()


@router.get("/metrics/text", response_class=PlainTextResponse)
async def diagnostics_metrics_text():
    from app.core.observability.metrics import get_metrics
    return get_metrics().prometheus_text()


# ── Traces ────────────────────────────────────────────────────────────────────

@router.get("/traces")
async def diagnostics_traces(n: int = 100):
    from app.core.observability.tracer import get_tracer
    return {"traces": get_tracer().recent(n)}


@router.get("/traces/active")
async def diagnostics_traces_active():
    from app.core.observability.tracer import get_tracer
    return {"active": get_tracer().active()}


@router.get("/traces/{trace_id}")
async def diagnostics_trace(trace_id: str):
    from app.core.observability.tracer import get_tracer
    spans = get_tracer().trace(trace_id)
    if not spans:
        raise HTTPException(404, f"Trace {trace_id!r} not found")
    return {"trace_id": trace_id, "spans": spans}


# ── Background services ───────────────────────────────────────────────────────

@router.get("/services")
async def diagnostics_services():
    from app.services.registry import get_service_registry
    return {"services": get_service_registry().status()}


@router.post("/services/{name}/start")
async def service_start(name: str):
    from app.services.registry import get_service_registry
    ok = get_service_registry().start(name)
    if not ok:
        raise HTTPException(404, f"Service '{name}' not found")
    return {"started": name}


@router.post("/services/{name}/stop")
async def service_stop(name: str):
    from app.services.registry import get_service_registry
    ok = get_service_registry().stop(name)
    if not ok:
        raise HTTPException(404, f"Service '{name}' not found")
    return {"stopped": name}


# ── Layered memory ────────────────────────────────────────────────────────────

@router.get("/memory")
async def diagnostics_memory(n: int = 50, kind: Optional[str] = None):
    from app.memory.layered import get_layered_memory
    mem     = get_layered_memory()
    records = mem.recent(n, kind=kind)
    return {
        "stats"  : mem.stats,
        "records": [r.to_dict() for r in reversed(records)],
    }


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 20
    kind : Optional[str] = None


@router.post("/memory/search")
async def diagnostics_memory_search(req: MemorySearchRequest):
    from app.memory.layered import get_layered_memory
    results = get_layered_memory().search(req.query, limit=req.limit, kind=req.kind)
    return {"count": len(results), "results": [r.to_dict() for r in results]}


# ── Code generation ───────────────────────────────────────────────────────────

@router.get("/codegen")
async def diagnostics_codegen():
    from app.codegen.pipeline import get_codegen_pipeline
    pending = get_codegen_pipeline().list_pending()
    return {"pending_count": len(pending), "pending": [r.to_dict() for r in pending]}


class ApproveRequest(BaseModel):
    approver: str = "api"


class RejectRequest(BaseModel):
    reason: str = ""


@router.post("/codegen/{run_id}/approve")
async def codegen_approve(run_id: str, req: ApproveRequest):
    from app.codegen.pipeline import get_codegen_pipeline
    result = get_codegen_pipeline().approve(run_id, approver=req.approver)
    if not result:
        raise HTTPException(404, f"Run {run_id!r} not found or not pending")
    return result.to_dict()


@router.post("/codegen/{run_id}/reject")
async def codegen_reject(run_id: str, req: RejectRequest):
    from app.codegen.pipeline import get_codegen_pipeline
    result = get_codegen_pipeline().reject(run_id, reason=req.reason)
    if not result:
        raise HTTPException(404, f"Run {run_id!r} not found or not rejectable")
    return result.to_dict()
