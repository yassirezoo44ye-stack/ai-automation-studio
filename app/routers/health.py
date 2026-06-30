import os
import shutil

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.db import get_pool
from app.core.config import WORKSPACES, DIST_DIR
from app.core.maintenance import _error_counts, ERROR_WINDOW_SEC, _maintenance_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    async with get_pool().acquire() as conn:
        pg_version = await conn.fetchval("SELECT version()")
    from datetime import datetime
    return {"status": "healthy", "db": "postgresql", "pg_version": pg_version,
            "timestamp": datetime.utcnow().isoformat()}


@router.get("/api/health/full")
async def health_full():
    """Self-diagnostic snapshot: DB, disk, secrets config, and recent error rates."""
    from datetime import datetime
    checks: dict = {}

    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    pool = get_pool()
    checks["db_pool"] = (
        {"size": pool.get_size(), "free": pool.get_idle_size()} if pool else "not initialized"
    )

    for label, path in (("workspaces_dir", WORKSPACES), ("dist_dir", DIST_DIR)):
        try:
            usage = shutil.disk_usage(path if path.exists() else path.parent)
            checks[label] = {"exists": path.exists(), "free_gb": round(usage.free / (1024 ** 3), 2)}
        except Exception as e:
            checks[label] = f"error: {e}"

    checks["session_secret_configured"]  = bool(os.getenv("SESSION_SECRET"))
    checks["anthropic_key_configured"]   = bool(os.getenv("ANTHROPIC_API_KEY"))
    checks["stripe_key_configured"]      = bool(os.getenv("STRIPE_SECRET_KEY"))
    checks["recent_errors"]              = dict(_error_counts)
    checks["error_window_sec"]           = ERROR_WINDOW_SEC
    checks["last_maintenance_run"]       = _maintenance_state["last_run"]
    checks["last_maintenance_result"]    = _maintenance_state["last_result"]

    overall_ok = checks["database"] == "ok" and checks["session_secret_configured"]
    return {"status": "healthy" if overall_ok else "degraded",
            "checks": checks, "timestamp": datetime.utcnow().isoformat()}
