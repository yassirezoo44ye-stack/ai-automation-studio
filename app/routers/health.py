"""
Health endpoints — Layer 13 surface.

GET /health              liveness probe  — is the process alive?
GET /health/ready        readiness probe — is the server ready for traffic?
GET /api/health/full     detailed diagnostic snapshot
GET /api/runtimes        runtime registry
"""
import os
import shutil
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app.core.config import WORKSPACES, DIST_DIR
from app.core.maintenance import _error_counts, ERROR_WINDOW_SEC, _maintenance_state

router   = APIRouter(tags=["health"])
_BOOT_AT = time.time()


# ── Liveness — fast; never touches DB ────────────────────────────────────────

@router.get("/health")
async def liveness():
    """
    Kubernetes liveness probe.
    Returns 200 as long as the process is alive and the event loop is running.
    """
    return {
        "status"    : "alive",
        "uptime_s"  : round(time.time() - _BOOT_AT, 1),
        "timestamp" : datetime.now(timezone.utc).isoformat(),
    }


# ── Readiness — checks critical dependencies ──────────────────────────────────

@router.get("/health/ready")
async def readiness():
    """
    Kubernetes readiness probe.
    Returns 200 only when the DB pool is healthy and required config is present.
    Returns 503 during startup or after catastrophic failure.
    """
    issues: list[str] = []

    # Database
    try:
        from app.core.db import get_pool
        pool = get_pool()
        if pool is None:
            issues.append("db_pool_not_initialized")
        else:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except Exception as exc:
        issues.append(f"db_unreachable: {exc}")

    # Required secrets
    if not os.getenv("SESSION_SECRET"):
        issues.append("SESSION_SECRET_missing")

    if issues:
        return JSONResponse(
            status_code = 503,
            content     = {"status": "not_ready", "issues": issues,
                           "timestamp": datetime.now(timezone.utc).isoformat()},
        )

    return {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Full diagnostic snapshot ──────────────────────────────────────────────────

@router.get("/api/health/full")
async def health_full():
    """Detailed self-diagnostic snapshot for ops dashboards."""
    checks: dict = {}

    # Database
    try:
        from app.core.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            pg_version = await conn.fetchval("SELECT version()")
        checks["database"] = "ok"
        checks["db_pool"]  = {
            "size": pool.get_size(),
            "idle": pool.get_idle_size(),
        }
        checks["pg_version"] = pg_version
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Cache backend
    try:
        from app.core.cache import get_redis
        cache = await get_redis()
        await cache.set("_health_probe", "1", ttl=5)
        checks["cache"] = cache.backend
    except Exception as e:
        checks["cache"] = f"error: {e}"

    # Disk
    for label, path in (("workspaces_dir", WORKSPACES), ("dist_dir", DIST_DIR)):
        try:
            usage = shutil.disk_usage(path if path.exists() else path.parent)
            checks[label] = {
                "exists" : path.exists(),
                "free_gb": round(usage.free / 1024 ** 3, 2),
            }
        except Exception as e:
            checks[label] = f"error: {e}"

    # Jobs
    try:
        from app.core.jobs import get_job_queue
        checks["jobs"] = await get_job_queue().stats()
    except Exception as e:
        checks["jobs"] = f"error: {e}"

    # WebSocket
    try:
        from app.routers.ws import manager as ws_manager
        checks["ws_connections"] = sum(len(v) for v in ws_manager._subs.values())
    except Exception:
        checks["ws_connections"] = 0

    # Config flags
    checks["config"] = {
        "session_secret" : bool(os.getenv("SESSION_SECRET")),
        "anthropic_key"  : bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai_key"     : bool(os.getenv("OPENAI_API_KEY")),
        "stripe_key"     : bool(os.getenv("STRIPE_SECRET_KEY")),
        "redis_url"      : bool(os.getenv("REDIS_URL")),
    }

    checks["errors"]          = dict(_error_counts)
    checks["error_window_sec"] = ERROR_WINDOW_SEC
    checks["maintenance"]     = _maintenance_state
    checks["uptime_s"]        = round(time.time() - _BOOT_AT, 1)

    ok = checks.get("database") == "ok" and checks["config"]["session_secret"]
    return {
        "status"   : "healthy" if ok else "degraded",
        "checks"   : checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Runtime registry ──────────────────────────────────────────────────────────

@router.get("/api/runtimes")
async def get_runtimes():
    from app.runtime import registry
    return {"runtimes": registry.to_dict()}
