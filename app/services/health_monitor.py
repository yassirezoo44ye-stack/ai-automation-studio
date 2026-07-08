"""Health Monitor Service — periodically checks all probes and updates metrics."""
from __future__ import annotations

import logging
from app.services.registry import BaseService

log = logging.getLogger(__name__)


class HealthMonitorService(BaseService):
    name        = "health_monitor"
    description = "Runs health probes every 30s and updates observability metrics"
    interval_s  = 30.0

    async def tick(self) -> None:
        from app.core.observability.health   import get_health_registry
        from app.core.observability.metrics  import get_metrics

        report  = await get_health_registry().check_all()
        metrics = get_metrics()

        unhealthy = sum(1 for p in report["probes"] if p["status"] == "unhealthy")
        degraded  = sum(1 for p in report["probes"] if p["status"] == "degraded")

        metrics.gauge("health_probes_unhealthy", "Unhealthy health probes").set(unhealthy)
        metrics.gauge("health_probes_degraded",  "Degraded health probes").set(degraded)

        if unhealthy:
            log.warning("Health monitor: %d probe(s) UNHEALTHY", unhealthy)
        elif degraded:
            log.info("Health monitor: %d probe(s) DEGRADED", degraded)
        else:
            log.debug("Health monitor: all probes HEALTHY")
