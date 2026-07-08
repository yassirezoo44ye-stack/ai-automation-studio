"""Performance Optimizer — identifies slow agents and suggests evolution targets."""
from __future__ import annotations

import logging
from app.services.registry import BaseService

log = logging.getLogger(__name__)

_SLOW_MS_THRESHOLD  = 5_000.0   # agents averaging > 5s are flagged
_ERROR_RATE_TRIGGER = 0.30       # agents with > 30% error rate trigger evolution


class PerformanceOptimizerService(BaseService):
    name        = "performance_optimizer"
    description = "Monitors agent performance and triggers evolution for underperformers (2-min interval)"
    interval_s  = 120.0
    auto_restart = True

    async def tick(self) -> None:
        from app.core.observability.metrics import get_metrics
        from app.agents.memory              import get_memory

        memory  = get_memory()
        metrics = get_metrics()
        stats   = memory.global_stats()

        slow_agents  : list[str] = []
        error_agents : list[str] = []

        for s in stats:
            if s.avg_ms > _SLOW_MS_THRESHOLD:
                slow_agents.append(s.name)
            if s.call_count >= 5 and (1 - s.success_rate) > _ERROR_RATE_TRIGGER:
                error_agents.append(s.name)

        metrics.gauge("performance_slow_agents",
                      "Agents exceeding latency threshold").set(len(slow_agents))
        metrics.gauge("performance_error_prone_agents",
                      "Agents exceeding error-rate threshold").set(len(error_agents))

        if error_agents:
            log.warning("Performance optimizer: high-error agents: %s — consider evolution",
                        error_agents)
        if slow_agents:
            log.warning("Performance optimizer: slow agents: %s", slow_agents)
        else:
            log.debug("Performance optimizer: all agents within thresholds")
