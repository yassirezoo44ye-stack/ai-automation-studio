"""
Registers one aggregate health probe into the EXISTING health registry
(app/core/observability/health.py) — matches how "AI providers", "event
bus", etc. are each represented as a single probe, not one per instance.
"""
from __future__ import annotations


async def _probe_integrations():
    from app.core.observability.health import HealthStatus, ProbeResult
    from app.integrations.retry import get_integration_circuit_breaker

    snapshot = get_integration_circuit_breaker().snapshot()
    open_count = sum(1 for c in snapshot.values() if c["state"] == "open")
    if not snapshot:
        return ProbeResult(name="integrations", status=HealthStatus.HEALTHY, message="no active connections")
    if open_count == 0:
        return ProbeResult(name="integrations", status=HealthStatus.HEALTHY,
                            message=f"{len(snapshot)} connection(s) tracked, none failing")
    if open_count < len(snapshot):
        return ProbeResult(name="integrations", status=HealthStatus.DEGRADED,
                            message=f"{open_count}/{len(snapshot)} connections failing",
                            metadata={"open_circuits": open_count, "total": len(snapshot)})
    return ProbeResult(name="integrations", status=HealthStatus.UNHEALTHY,
                        message=f"all {len(snapshot)} tracked connections are failing",
                        metadata={"open_circuits": open_count, "total": len(snapshot)})


def register_integration_health_probe() -> None:
    from app.core.observability.health import get_health_registry
    get_health_registry().register("integrations", _probe_integrations, critical=False, timeout_s=2.0)
