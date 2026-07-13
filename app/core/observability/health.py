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

    async def probe_redis() -> ProbeResult:
        try:
            from app.core.cache import get_redis
            cache = await get_redis()
            if cache.backend != "redis":
                return ProbeResult(
                    name="redis", status=HealthStatus.DEGRADED,
                    message="REDIS_URL not set — using in-process cache fallback",
                    metadata={"backend": cache.backend},
                )
            await cache.set("_health_probe", "1", ttl=5)
            return ProbeResult(name="redis", status=HealthStatus.HEALTHY,
                               message="Redis OK", metadata={"backend": cache.backend})
        except Exception as exc:
            return ProbeResult(name="redis", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_ai_providers() -> ProbeResult:
        try:
            from app.core.ai.registry.registry import platform_registry
            snapshot  = platform_registry.health()
            available = [pid for pid, info in snapshot.items() if info["available"]]
            if not available:
                return ProbeResult(name="ai_providers", status=HealthStatus.DEGRADED,
                                   message="no AI provider configured", metadata=snapshot)
            return ProbeResult(name="ai_providers", status=HealthStatus.HEALTHY,
                               message=f"{len(available)} provider(s) available", metadata=snapshot)
        except Exception as exc:
            return ProbeResult(name="ai_providers", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_event_bus() -> ProbeResult:
        try:
            from app.core.events import get_event_bus
            stats = get_event_bus().stats()
            return ProbeResult(name="event_bus", status=HealthStatus.HEALTHY,
                               message=f"backend={stats['backend']}", metadata=stats)
        except Exception as exc:
            return ProbeResult(name="event_bus", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_marketplace() -> ProbeResult:
        try:
            from app.marketplace.store import get_marketplace_store, JsonMarketplaceStore
            store = get_marketplace_store()
            count = await store.count()
            if isinstance(store, JsonMarketplaceStore):
                return ProbeResult(name="marketplace", status=HealthStatus.DEGRADED,
                                   message="using JSON fallback store (no DB pool yet)",
                                   metadata={"items": count})
            return ProbeResult(name="marketplace", status=HealthStatus.HEALTHY,
                               message=f"{count} listing(s)", metadata={"items": count})
        except Exception as exc:
            return ProbeResult(name="marketplace", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_billing() -> ProbeResult:
        try:
            from app.billing import get_usage_service
            import os as _os
            svc = get_usage_service()
            if svc._pool is None:
                return ProbeResult(name="billing", status=HealthStatus.UNHEALTHY,
                                   message="UsageService has no DB pool")
            if not _os.getenv("STRIPE_SECRET_KEY"):
                return ProbeResult(name="billing", status=HealthStatus.DEGRADED,
                                   message="STRIPE_SECRET_KEY not set — checkout/portal disabled")
            return ProbeResult(name="billing", status=HealthStatus.HEALTHY, message="billing OK")
        except Exception as exc:
            return ProbeResult(name="billing", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_plugin_loader() -> ProbeResult:
        try:
            from app.plugins.loader import get_plugin_loader
            loader = get_plugin_loader()
            n = len(loader._instances)
            return ProbeResult(name="plugin_loader", status=HealthStatus.HEALTHY,
                               message=f"{n} active plugin instance(s)", metadata={"active": n})
        except Exception as exc:
            return ProbeResult(name="plugin_loader", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_storage() -> ProbeResult:
        try:
            import shutil
            from app.core.config import WORKSPACES
            path  = WORKSPACES if WORKSPACES.exists() else WORKSPACES.parent
            usage = shutil.disk_usage(path)
            free_gb = usage.free / 1024 ** 3
            if free_gb < 1.0:
                return ProbeResult(name="storage", status=HealthStatus.DEGRADED,
                                   message=f"low disk space: {free_gb:.2f}GB free",
                                   metadata={"free_gb": round(free_gb, 2)})
            return ProbeResult(name="storage", status=HealthStatus.HEALTHY,
                               message=f"{free_gb:.2f}GB free", metadata={"free_gb": round(free_gb, 2)})
        except Exception as exc:
            return ProbeResult(name="storage", status=HealthStatus.DEGRADED, message=str(exc))

    async def probe_vector_db() -> ProbeResult:
        try:
            from app.memory.semantic import get_semantic_memory
            mem = await get_semantic_memory()
            if not mem._pgvector:
                return ProbeResult(name="vector_db", status=HealthStatus.DEGRADED,
                                   message="pgvector unavailable — using TF-IDF fallback")
            return ProbeResult(name="vector_db", status=HealthStatus.HEALTHY, message="pgvector OK")
        except Exception as exc:
            return ProbeResult(name="vector_db", status=HealthStatus.DEGRADED, message=str(exc))

    hr.register("agent_kernel",       probe_kernel,   critical=True,  timeout_s=3.0)
    hr.register("agent_memory",       probe_memory,   critical=False, timeout_s=2.0)
    hr.register("background_services",probe_services, critical=False, timeout_s=2.0)
    hr.register("redis",              probe_redis,        critical=False, timeout_s=3.0)
    hr.register("ai_providers",       probe_ai_providers, critical=False, timeout_s=3.0)
    hr.register("event_bus",          probe_event_bus,    critical=False, timeout_s=2.0)
    hr.register("marketplace",        probe_marketplace,  critical=False, timeout_s=3.0)
    hr.register("billing",            probe_billing,      critical=False, timeout_s=3.0)
    hr.register("plugin_loader",      probe_plugin_loader,critical=False, timeout_s=2.0)
    hr.register("storage",            probe_storage,      critical=False, timeout_s=2.0)
    hr.register("vector_db",          probe_vector_db,    critical=False, timeout_s=3.0)
