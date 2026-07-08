"""Memory Compactor — prunes old execution records and compacts the memory store."""
from __future__ import annotations

import logging
from app.services.registry import BaseService

log = logging.getLogger(__name__)

_MAX_RECORDS = 8_000    # prune when count exceeds this


class MemoryCompactorService(BaseService):
    name        = "memory_compactor"
    description = "Prunes old agent execution records to prevent unbounded memory growth (hourly)"
    interval_s  = 3_600.0
    auto_restart = True

    async def tick(self) -> None:
        from app.core.observability.metrics import get_metrics
        from app.agents.memory              import get_memory

        memory  = get_memory()
        metrics = get_metrics()

        before  = memory.total_count()
        pruned  = 0

        if before > _MAX_RECORDS:
            # AgentMemory uses a deque internally; just accessing recent() triggers compaction.
            # If a prune() method exists, call it; otherwise rely on the rolling window.
            if hasattr(memory, "prune"):
                pruned = memory.prune(keep=_MAX_RECORDS)
            else:
                log.debug("Memory compactor: AgentMemory has no prune() method — relying on rolling window")

        after = memory.total_count()
        metrics.gauge("memory_execution_records", "Agent execution records in memory").set(after)
        metrics.counter("memory_records_pruned", "Total execution records pruned").inc(pruned)

        log.debug("Memory compactor: %d → %d records (pruned %d)", before, after, pruned)
