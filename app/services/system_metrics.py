"""
SystemMetricsService — periodic sampler feeding MetricsRegistry gauges that
can't be updated event-by-event: OS resource usage (psutil) and sandbox
worker state (a DB snapshot, not an event stream). Every other new metric
in this phase is emitted directly from an existing event (see
app/core/observability/bridges.py); this service exists only for the
handful of metrics that are inherently "current state," not "count of
things that happened."
"""
from __future__ import annotations

import logging

from app.services.registry import BaseService

log = logging.getLogger(__name__)


class SystemMetricsService(BaseService):
    name         = "system_metrics"
    description  = "Samples CPU/memory/disk/network/FD usage and sandbox worker state into MetricsRegistry"
    interval_s   = 15.0
    auto_restart = True

    def __init__(self) -> None:
        super().__init__()
        # psutil.Process.cpu_percent(interval=None) reports usage as a delta
        # since the LAST call on this same Process instance — a fresh
        # Process() every tick has no prior baseline and always returns 0.0.
        # Keep one instance alive across ticks so the delta is meaningful.
        self._proc = None

    async def tick(self) -> None:
        from app.core.observability.metrics import get_metrics
        m = get_metrics()
        self._sample_system(m)
        await self._sample_sandbox(m)

    def _sample_system(self, m) -> None:
        try:
            import psutil
        except Exception as exc:
            log.debug("system_metrics: psutil unavailable: %s", exc)
            return

        if self._proc is None:
            self._proc = psutil.Process()
            self._proc.cpu_percent(interval=None)  # prime the baseline; first real reading comes next tick

        try:
            m.gauge("system_cpu_percent", "Process CPU utilisation percent").set(
                self._proc.cpu_percent(interval=None)
            )
            mem = self._proc.memory_info()
            m.gauge("system_memory_rss_mb", "Process resident memory in MB").set(
                round(mem.rss / 1024 ** 2, 1)
            )
            disk = psutil.disk_usage("/")
            m.gauge("system_disk_used_percent", "Disk utilisation percent").set(disk.percent)
            net = psutil.net_io_counters()
            m.gauge("system_network_bytes_sent", "Cumulative bytes sent").set(net.bytes_sent)
            m.gauge("system_network_bytes_recv", "Cumulative bytes received").set(net.bytes_recv)
            try:
                m.gauge("system_open_fds", "Open file descriptors (process)").set(
                    self._proc.num_fds()
                )
            except AttributeError:
                pass  # num_fds() is POSIX-only; skip on platforms without it (e.g. Windows)
        except Exception as exc:
            log.warning("system_metrics: sampling failed: %s", exc)

    async def _sample_sandbox(self, m) -> None:
        try:
            from app.core.db import get_pool
            pool = get_pool()
            if pool is None:
                return
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT
                         count(*) FILTER (WHERE status = 'running') AS running,
                         count(*) FILTER (WHERE status = 'crashed') AS crashed,
                         COALESCE(sum(cpu_seconds_used) FILTER (WHERE status = 'running'), 0) AS cpu_s,
                         COALESCE(sum(memory_mb_peak)   FILTER (WHERE status = 'running'), 0) AS mem_mb
                       FROM sandbox_workers"""
                )
            if row is None:
                return
            m.gauge("sandbox_running_workers", "Currently running sandbox workers").set(row["running"])
            m.gauge("sandbox_execution_failures", "Sandbox workers in crashed state").set(row["crashed"])
            m.gauge("sandbox_cpu_seconds", "Total CPU seconds used by running sandbox workers").set(float(row["cpu_s"]))
            m.gauge("sandbox_memory_mb", "Total memory MB used by running sandbox workers").set(float(row["mem_mb"]))
        except Exception as exc:
            log.debug("system_metrics: sandbox sampling skipped: %s", exc)
