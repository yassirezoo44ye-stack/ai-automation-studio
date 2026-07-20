"""
Registers a dedicated sandbox-worker health probe into the EXISTING health
registry (app/core/observability/health.py) — matches
app/integrations/health.py's pattern. Separate from that module's existing
"plugin_loader" probe (which only reports an active-instance count from
PluginLoader's in-memory dict); this one reports the actual crash ratio of
sandbox_workers rows (migration 008), the gap identified in the Plugin SDK
audit.
"""
from __future__ import annotations

_LOOKBACK = "1 hour"


async def _probe_sandbox_workers():
    from app.core.db import get_pool
    from app.core.observability.health import HealthStatus, ProbeResult

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"SELECT status, COUNT(*) AS n FROM sandbox_workers "
            f"WHERE started_at > NOW() - INTERVAL '{_LOOKBACK}' GROUP BY status"
        )
    counts = {r["status"]: r["n"] for r in rows}
    total = sum(counts.values())
    crashed = counts.get("crashed", 0)

    if total == 0:
        return ProbeResult(name="sandbox_workers", status=HealthStatus.HEALTHY,
                            message=f"no sandbox workers spawned in the last {_LOOKBACK}")

    ratio = crashed / total
    metadata = {"total": total, "crashed": crashed, "crash_ratio": round(ratio, 2)}
    if ratio == 0:
        return ProbeResult(name="sandbox_workers", status=HealthStatus.HEALTHY,
                            message=f"{total} worker(s) in the last {_LOOKBACK}, none crashed", metadata=metadata)
    if ratio < 0.5:
        return ProbeResult(name="sandbox_workers", status=HealthStatus.DEGRADED,
                            message=f"{crashed}/{total} sandbox workers crashed in the last {_LOOKBACK}",
                            metadata=metadata)
    return ProbeResult(name="sandbox_workers", status=HealthStatus.UNHEALTHY,
                        message=f"{crashed}/{total} sandbox workers crashed in the last {_LOOKBACK}",
                        metadata=metadata)


def register_sandbox_health_probe() -> None:
    from app.core.observability.health import get_health_registry
    get_health_registry().register("sandbox_workers", _probe_sandbox_workers, critical=False, timeout_s=3.0)
