"""
Prometheus metrics endpoint — Layer 13 surface.

GET /metrics   returns text/plain Prometheus exposition format

Exposes:
  axon_http_requests_total{method, path, status}
  axon_http_request_duration_seconds{method, path, quantile}
  axon_agent_executions_total{agent, status}
  axon_plans_total
  axon_jobs_total{kind, status}
  axon_cache_hits_total{backend}
  axon_cache_misses_total{backend}
  axon_ws_connections_active
  axon_db_pool_size
  axon_db_pool_idle
  process_uptime_seconds
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["metrics"])

_START_TIME = time.time()

# ── Counters (written by middleware / other modules) ──────────────────────────

http_requests_total   : dict[tuple, int] = defaultdict(int)   # (method, path, status)
http_durations        : dict[tuple, list[float]] = defaultdict(list)  # (method, path) → [s]
agent_executions_total: dict[tuple, int] = defaultdict(int)   # (agent, status)
plans_total           : int = 0
cache_hits            : dict[str, int] = defaultdict(int)     # backend
cache_misses          : dict[str, int] = defaultdict(int)


def record_http(method: str, path: str, status: int, duration_s: float) -> None:
    http_requests_total[(method, path, str(status))] += 1
    http_durations[(method, path)].append(duration_s)
    # Keep only the last 1000 samples per route to bound memory
    if len(http_durations[(method, path)]) > 1000:
        http_durations[(method, path)] = http_durations[(method, path)][-500:]

    # Also feed the coarse (unlabeled) MetricsRegistry counters that
    # /api/diagnostics/metrics reads — these were pre-registered in
    # _wire_defaults() but never incremented anywhere, which is worse than
    # not having them (a scrape that always reads 0 looks like "no
    # traffic" instead of "not wired"). This is the one call site that
    # already has every request's method/path/status/duration, so it
    # feeds both stores instead of adding a second middleware.
    from app.core.observability.metrics import get_metrics
    m = get_metrics()
    m.counter("http_requests_total").inc()
    m.histogram("http_request_duration_ms").observe(duration_s * 1000)
    if status >= 500:
        m.counter("http_errors_total").inc()


def record_agent(agent: str, status: str) -> None:
    agent_executions_total[(agent, status)] += 1


def record_plan() -> None:
    global plans_total
    plans_total += 1


def record_cache(backend: str, hit: bool) -> None:
    if hit:
        cache_hits[backend] += 1
    else:
        cache_misses[backend] += 1


# ── Prometheus text format helpers ────────────────────────────────────────────

def _labels(**kv) -> str:
    parts = ','.join(f'{k}="{v}"' for k, v in kv.items())
    return f"{{{parts}}}"


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(q * len(s))
    return s[min(idx, len(s) - 1)]


def _build_metrics() -> str:
    lines: list[str] = []

    # ── HTTP requests ─────────────────────────────────────────────────────────
    lines.append("# HELP axon_http_requests_total Total HTTP requests")
    lines.append("# TYPE axon_http_requests_total counter")
    for (method, path, status), count in http_requests_total.items():
        lbl = _labels(method=method, path=path, status=status)
        lines.append(f"axon_http_requests_total{lbl} {count}")

    # ── HTTP latency ──────────────────────────────────────────────────────────
    lines.append("# HELP axon_http_request_duration_seconds HTTP request latency")
    lines.append("# TYPE axon_http_request_duration_seconds summary")
    for (method, path), durs in http_durations.items():
        for q in (0.5, 0.9, 0.99):
            lbl = _labels(method=method, path=path, quantile=str(q))
            lines.append(f"axon_http_request_duration_seconds{lbl} {_quantile(durs, q):.6f}")
        lbl_sum   = _labels(method=method, path=path)
        lines.append(f"axon_http_request_duration_seconds_sum{lbl_sum} {sum(durs):.6f}")
        lines.append(f"axon_http_request_duration_seconds_count{lbl_sum} {len(durs)}")

    # ── Agent executions ──────────────────────────────────────────────────────
    lines.append("# HELP axon_agent_executions_total Agent run count by name and status")
    lines.append("# TYPE axon_agent_executions_total counter")
    for (agent, status), count in agent_executions_total.items():
        lbl = _labels(agent=agent, status=status)
        lines.append(f"axon_agent_executions_total{lbl} {count}")

    # ── Plans ─────────────────────────────────────────────────────────────────
    lines.append("# HELP axon_plans_total Total planning engine invocations")
    lines.append("# TYPE axon_plans_total counter")
    lines.append(f"axon_plans_total {plans_total}")

    # ── Cache ─────────────────────────────────────────────────────────────────
    lines.append("# HELP axon_cache_hits_total Cache hits by backend")
    lines.append("# TYPE axon_cache_hits_total counter")
    for backend, count in cache_hits.items():
        lines.append(f'axon_cache_hits_total{{backend="{backend}"}} {count}')
    lines.append("# HELP axon_cache_misses_total Cache misses by backend")
    lines.append("# TYPE axon_cache_misses_total counter")
    for backend, count in cache_misses.items():
        lines.append(f'axon_cache_misses_total{{backend="{backend}"}} {count}')

    # ── Background jobs ───────────────────────────────────────────────────────
    lines.append("# HELP axon_jobs_total Background jobs by kind and status")
    lines.append("# TYPE axon_jobs_total counter")
    try:
        import asyncio
        from app.core.jobs import get_job_queue
        # Sync approximation — use stored counts
        queue = get_job_queue()
        active = len(queue._active)
        lines.append(f'axon_jobs_active {active}')
    except Exception:
        pass

    # ── WebSocket connections ─────────────────────────────────────────────────
    lines.append("# HELP axon_ws_connections_active Active WebSocket connections")
    lines.append("# TYPE axon_ws_connections_active gauge")
    try:
        from app.routers.ws import manager as ws_manager
        total_subs = sum(len(v) for v in ws_manager._subs.values())
        lines.append(f"axon_ws_connections_active {total_subs}")
    except Exception:
        lines.append("axon_ws_connections_active 0")

    # ── DB pool ───────────────────────────────────────────────────────────────
    lines.append("# HELP axon_db_pool_size DB connection pool size")
    lines.append("# TYPE axon_db_pool_size gauge")
    lines.append("# HELP axon_db_pool_idle DB connection pool idle connections")
    lines.append("# TYPE axon_db_pool_idle gauge")
    try:
        from app.core.db import get_pool
        pool = get_pool()
        if pool:
            lines.append(f"axon_db_pool_size {pool.get_size()}")
            lines.append(f"axon_db_pool_idle {pool.get_idle_size()}")
    except Exception:
        pass

    # ── Process ───────────────────────────────────────────────────────────────
    lines.append("# HELP process_uptime_seconds Seconds since server started")
    lines.append("# TYPE process_uptime_seconds gauge")
    lines.append(f"process_uptime_seconds {time.time() - _START_TIME:.1f}")

    return "\n".join(lines) + "\n"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-compatible metrics in text exposition format."""
    return PlainTextResponse(
        content      = _build_metrics(),
        media_type   = "text/plain; version=0.0.4; charset=utf-8",
    )
