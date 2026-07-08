"""
HealthRegistry — centralised health-check registry.

Every subsystem registers a named probe. The /api/health/detailed endpoint
calls all probes and returns an aggregated status.

Design principles:
  - Probes are async to support DB/network checks.
  - Each probe has a configurable timeout (default 5s).
  - A single UNHEALTHY probe makes the overall status DEGRADED.
  - Two or more UNHEALTHY → overall UNHEALTHY.
  - Probes are called in parallel.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN   = "unknown"


@dataclass
class ProbeResult:
    name      : str
    status    : HealthStatus
    message   : str = ""
    duration_ms: float = 0.0
    metadata  : dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name"       : self.name,
            "status"     : self.status.value,
            "message"    : self.message,
            "duration_ms": round(self.duration_ms, 1),
            "metadata"   : self.metadata,
        }


ProbeFunc = Callable[[], Awaitable[ProbeResult]]


@dataclass
class _ProbeEntry:
    name     : str
    fn       : ProbeFunc
    timeout_s: float = 5.0
    critical : bool  = True   # if False, failure → DEGRADED not UNHEALTHY


class HealthRegistry:
    """
    Register and run health probes.

    Usage:
        hr = get_health_registry()
        hr.register("database", probe_fn, critical=True)
        report = await hr.check_all()
    """

    def __init__(self) -> None:
        self._probes: dict[str, _ProbeEntry] = {}

    def register(
        self,
        name     : str,
        probe    : ProbeFunc,
        *,
        timeout_s: float = 5.0,
        critical : bool  = True,
    ) -> None:
        self._probes[name] = _ProbeEntry(name=name, fn=probe,
                                          timeout_s=timeout_s, critical=critical)
        log.debug("Health probe registered: %s (critical=%s)", name, critical)

    def unregister(self, name: str) -> None:
        self._probes.pop(name, None)

    async def _run_probe(self, entry: _ProbeEntry) -> ProbeResult:
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(entry.fn(), timeout=entry.timeout_s)
            result.duration_ms = (time.perf_counter() - t0) * 1000
            return result
        except asyncio.TimeoutError:
            return ProbeResult(
                name=entry.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Timed out after {entry.timeout_s}s",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            log.error("Health probe '%s' raised: %s", entry.name, exc)
            return ProbeResult(
                name=entry.name,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    async def check_all(self) -> dict:
        if not self._probes:
            return {
                "status" : HealthStatus.HEALTHY.value,
                "probes" : [],
                "ts"     : time.time(),
            }

        results = await asyncio.gather(*[
            self._run_probe(e) for e in self._probes.values()
        ])

        unhealthy_critical = sum(
            1 for r in results
            if r.status == HealthStatus.UNHEALTHY and self._probes[r.name].critical
        )
        any_degraded = any(
            r.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
            for r in results
        )

        if unhealthy_critical >= 2:
            overall = HealthStatus.UNHEALTHY
        elif unhealthy_critical == 1 or any_degraded:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return {
            "status" : overall.value,
            "probes" : [r.to_dict() for r in results],
            "ts"     : time.time(),
        }

    async def check(self, name: str) -> Optional[ProbeResult]:
        entry = self._probes.get(name)
        if not entry:
            return None
        return await self._run_probe(entry)

    @property
    def probe_names(self) -> list[str]:
        return list(self._probes.keys())


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: HealthRegistry | None = None


def get_health_registry() -> HealthRegistry:
    global _registry
    if _registry is None:
        _registry = HealthRegistry()
        _register_defaults(_registry)
    return _registry


def _register_defaults(hr: HealthRegistry) -> None:
    """Register built-in liveness probes."""

    async def probe_kernel() -> ProbeResult:
        try:
            from app.agents.kernel import get_agent_kernel
            k = get_agent_kernel()
            n = len(k.all_agents())
            return ProbeResult(
                name="agent_kernel",
                status=HealthStatus.HEALTHY if k._booted else HealthStatus.DEGRADED,
                message=f"{n} agents registered",
                metadata={"agent_count": n, "booted": k._booted},
            )
        except Exception as exc:
            return ProbeResult(name="agent_kernel", status=HealthStatus.UNHEALTHY, message=str(exc))

    async def probe_memory() -> ProbeResult:
        try:
            from app.agents.memory import get_memory
            m   = get_memory()
            tot = m.total_count()
            return ProbeResult(
                name="agent_memory",
                status=HealthStatus.HEALTHY,
                message=f"{tot} execution records",
                metadata={"total": tot},
            )
        except Exception as exc:
            return ProbeResult(name="agent_memory", status=HealthStatus.UNHEALTHY, message=str(exc))

    async def probe_services() -> ProbeResult:
        try:
            from app.services.registry import get_service_registry
            reg     = get_service_registry()
            running = reg.running_count()
            total   = reg.total_count()
            return ProbeResult(
                name="background_services",
                status=HealthStatus.HEALTHY,
                message=f"{running}/{total} services running",
                metadata={"running": running, "total": total},
            )
        except Exception as exc:
            return ProbeResult(name="background_services",
                               status=HealthStatus.DEGRADED, message=str(exc))

    hr.register("agent_kernel",       probe_kernel,   critical=True,  timeout_s=3.0)
    hr.register("agent_memory",       probe_memory,   critical=False, timeout_s=2.0)
    hr.register("background_services",probe_services, critical=False, timeout_s=2.0)
