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
from pydantic import BaseModel, field_validator

from app.core.ssrf_guard import UnsafeUrlError, assert_public_url

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


# ── Alerting ──────────────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str
    rule_type: str            # gauge_above | counter_rate_above | health_unhealthy
    target: str
    threshold: Optional[float] = None
    notify_email: Optional[str] = None
    notify_webhook_url: Optional[str] = None
    enabled: bool = True

    @field_validator("notify_webhook_url")
    @classmethod
    def _webhook_must_be_public(cls, v: Optional[str]) -> Optional[str]:
        # Blocks SSRF via a rule whose webhook points at an internal
        # service or the cloud metadata endpoint (169.254.169.254) — the
        # tick loop (app/services/alerting.py) would otherwise POST to
        # whatever URL is stored here with no further checks.
        if v:
            try:
                assert_public_url(v)
            except UnsafeUrlError as exc:
                raise ValueError(f"notify_webhook_url is not allowed: {exc}") from exc
        return v


@router.get("/alerts/rules")
async def list_alert_rules():
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM alert_rules ORDER BY created_at")
    return {"rules": [dict(r) for r in rows]}


@router.post("/alerts/rules", status_code=201)
async def create_alert_rule(body: AlertRuleCreate):
    if body.rule_type not in ("gauge_above", "counter_rate_above", "health_unhealthy"):
        raise HTTPException(400, "Invalid rule_type")
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO alert_rules (name, rule_type, target, threshold, notify_email, notify_webhook_url, enabled) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
            body.name, body.rule_type, body.target, body.threshold,
            body.notify_email, body.notify_webhook_url, body.enabled,
        )
    return dict(row)


@router.post("/alerts/rules/{rule_id}/toggle")
async def toggle_alert_rule(rule_id: str, enabled: bool):
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE alert_rules SET enabled=$2, updated_at=NOW() WHERE id=$1 RETURNING *",
            rule_id, enabled,
        )
    if row is None:
        raise HTTPException(404, f"Alert rule {rule_id!r} not found")
    return dict(row)


@router.get("/alerts/history")
async def alert_history(limit: int = 100, open_only: bool = False):
    from app.core.db import get_pool
    query = "SELECT h.*, r.name AS rule_name FROM alert_history h JOIN alert_rules r ON r.id = h.rule_id"
    if open_only:
        query += " WHERE h.resolved_at IS NULL"
    query += " ORDER BY h.fired_at DESC LIMIT $1"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, min(limit, 500))
    return {"history": [dict(r) for r in rows]}


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
