"""
ServiceRegistry — manages autonomous background services.

Each service is independently startable and stoppable.
Services run as asyncio Tasks and can be restarted on failure.

Built-in services (registered by factory.py lifespan):
  - health_monitor
  - dependency_monitor
  - security_monitor
  - performance_optimizer
  - memory_compactor
  - reflection_loop       (wraps existing ImprovementLoop)

Design:
  - Services expose start() / stop() / health()
  - Registry holds asyncio.Task handles
  - /api/services/* endpoints can start/stop individual services
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class ServiceState(str, Enum):
    STOPPED  = "stopped"
    STARTING = "starting"
    RUNNING  = "running"
    STOPPING = "stopping"
    FAILED   = "failed"


@dataclass
class ServiceHealth:
    name     : str
    state    : ServiceState
    uptime_s : float = 0.0
    restarts : int   = 0
    last_tick: Optional[float] = None
    error    : Optional[str]   = None

    def to_dict(self) -> dict:
        return {
            "name"     : self.name,
            "state"    : self.state.value,
            "uptime_s" : round(self.uptime_s, 1),
            "restarts" : self.restarts,
            "last_tick": self.last_tick,
            "error"    : self.error,
        }


class BaseService(ABC):
    """All background services extend this."""

    name: str = "unnamed_service"
    description: str = ""
    interval_s: float = 60.0      # seconds between ticks
    auto_restart: bool = True     # restart if the task crashes

    def __init__(self) -> None:
        self._task       : Optional[asyncio.Task] = None
        self._stop_event : asyncio.Event          = asyncio.Event()
        self._started_at : Optional[float]        = None
        self._last_tick  : Optional[float]        = None
        self._restarts   : int                    = 0
        self._last_error : Optional[str]          = None

    # ── Override in subclass ──────────────────────────────────────────────────

    @abstractmethod
    async def tick(self) -> None:
        """Called once per interval. Must be non-blocking (use asyncio)."""
        ...

    async def on_start(self) -> None:
        """Called once when the service starts."""

    async def on_stop(self) -> None:
        """Called once when the service stops cleanly."""

    # ── Lifecycle (do not override) ───────────────────────────────────────────

    async def _loop(self) -> None:
        self._stop_event.clear()
        self._started_at = time.monotonic()
        log.info("Service starting: %s", self.name)
        try:
            await self.on_start()
            while not self._stop_event.is_set():
                try:
                    await self.tick()
                    self._last_tick = time.monotonic()
                except Exception as exc:
                    log.error("Service '%s' tick error: %s", self.name, exc)
                    self._last_error = str(exc)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval_s
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            log.info("Service stopping: %s", self.name)
            try:
                await self.on_stop()
            except Exception as exc:
                log.error("Service '%s' on_stop error: %s", self.name, exc)

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.ensure_future(self._loop())
        self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self._last_error = str(exc)
            log.error("Service '%s' crashed: %s", self.name, exc)
            if self.auto_restart:
                self._restarts += 1
                log.info("Service '%s' auto-restarting (restart #%d)", self.name, self._restarts)
                self.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()

    @property
    def state(self) -> ServiceState:
        if self._task is None:
            return ServiceState.STOPPED
        if self._task.done():
            return ServiceState.FAILED if self._task.exception() else ServiceState.STOPPED
        if self._stop_event.is_set():
            return ServiceState.STOPPING
        if self._started_at is not None:
            return ServiceState.RUNNING
        return ServiceState.STARTING

    def health(self) -> ServiceHealth:
        uptime = (time.monotonic() - self._started_at) if self._started_at else 0.0
        return ServiceHealth(
            name=self.name,
            state=self.state,
            uptime_s=uptime,
            restarts=self._restarts,
            last_tick=self._last_tick,
            error=self._last_error,
        )


# ── Registry ──────────────────────────────────────────────────────────────────

class ServiceRegistry:
    """Holds and manages all background services."""

    def __init__(self) -> None:
        self._services: dict[str, BaseService] = {}

    def register(self, service: BaseService) -> None:
        self._services[service.name] = service
        log.debug("Service registered: %s", service.name)

    def get(self, name: str) -> Optional[BaseService]:
        return self._services.get(name)

    def start(self, name: str) -> bool:
        svc = self._services.get(name)
        if not svc:
            return False
        svc.start()
        return True

    def stop(self, name: str) -> bool:
        svc = self._services.get(name)
        if not svc:
            return False
        svc.stop()
        return True

    def start_all(self) -> int:
        count = 0
        for svc in self._services.values():
            svc.start()
            count += 1
        return count

    def stop_all(self) -> None:
        for svc in self._services.values():
            svc.stop()

    def running_count(self) -> int:
        return sum(1 for s in self._services.values() if s.state == ServiceState.RUNNING)

    def total_count(self) -> int:
        return len(self._services)

    def status(self) -> list[dict]:
        return [s.health().to_dict() for s in self._services.values()]

    def status_one(self, name: str) -> Optional[dict]:
        svc = self._services.get(name)
        return svc.health().to_dict() if svc else None


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
        _register_defaults(_registry)
    return _registry


def _register_defaults(reg: ServiceRegistry) -> None:
    from app.services.health_monitor       import HealthMonitorService
    from app.services.dependency_monitor   import DependencyMonitorService
    from app.services.security_monitor     import SecurityMonitorService
    from app.services.performance_optimizer import PerformanceOptimizerService
    from app.services.memory_compactor     import MemoryCompactorService
    from app.services.system_metrics       import SystemMetricsService

    reg.register(HealthMonitorService())
    reg.register(DependencyMonitorService())
    reg.register(SecurityMonitorService())
    reg.register(PerformanceOptimizerService())
    reg.register(MemoryCompactorService())
    reg.register(SystemMetricsService())
