"""
Continuous Self-Improvement Loop — runs as a background asyncio task.

Every `interval_s` seconds:
  1. Check memory for underperforming agents
  2. If error_rate > threshold → trigger evolution
  3. If evolution_count mod 5 == 0 → suggest new features
  4. Emit a LoopTick event to the kernel (for monitoring)

The loop is non-invasive: it only reads memory and calls the evolution engine.
It never blocks the main request path.

Start it with:
    loop = ImprovementLoop(kernel)
    asyncio.create_task(loop.start())

Stop it with:
    loop.stop()
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.kernel import AgentKernel

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL   = 60.0    # seconds between checks
_ERROR_THRESHOLD    = 0.25    # evolve when error rate exceeds this
_MIN_EXECUTIONS     = 10      # don't check until at least N executions


@dataclass
class LoopTick:
    tick           : int
    timestamp      : float = field(default_factory=time.time)
    error_rate     : float = 0.0
    action         : str   = "idle"    # idle | evolved | suggested | skipped
    evolved_agents : list[str] = field(default_factory=list)
    new_suggestions: int   = 0
    duration_ms    : float = 0.0

    def to_dict(self) -> dict:
        return {
            "tick"           : self.tick,
            "timestamp"      : self.timestamp,
            "error_rate"     : round(self.error_rate, 3),
            "action"         : self.action,
            "evolved_agents" : self.evolved_agents,
            "new_suggestions": self.new_suggestions,
            "duration_ms"    : round(self.duration_ms, 1),
        }


class ImprovementLoop:
    """Background continuous-improvement loop for the Agentic OS."""

    def __init__(
        self,
        kernel    : "AgentKernel",
        interval_s: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._kernel     = kernel
        self._interval   = interval_s
        self._running    = False
        self._tick       = 0
        self._history    : list[LoopTick] = []
        self._task       : Optional[asyncio.Task] = None
        self._evolution_count = 0

    # ── Public ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run the improvement loop until stop() is called."""
        self._running = True
        log.info("ImprovementLoop started (interval=%.0fs)", self._interval)
        while self._running:
            await asyncio.sleep(self._interval)
            if not self._running:
                break
            tick = await self._run_tick()
            self._history.append(tick)
            if len(self._history) > 50:
                self._history = self._history[-50:]

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    def schedule(self, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task:
        """Create and store the asyncio task."""
        self._task = asyncio.ensure_future(self.start())
        return self._task

    def last_tick(self) -> Optional[LoopTick]:
        return self._history[-1] if self._history else None

    def history(self, n: int = 10) -> list[dict]:
        return [t.to_dict() for t in self._history[-n:]]

    def stats(self) -> dict:
        return {
            "running"          : self._running,
            "tick_count"       : self._tick,
            "interval_s"       : self._interval,
            "evolution_cycles" : self._evolution_count,
            "last_tick"        : self.last_tick().to_dict() if self.last_tick() else None,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _run_tick(self) -> LoopTick:
        self._tick += 1
        t0   = time.perf_counter()
        tick = LoopTick(tick=self._tick)

        memory = self._kernel._memory
        total  = memory.total_count()

        if total < _MIN_EXECUTIONS:
            tick.action = "skipped"
            tick.duration_ms = (time.perf_counter() - t0) * 1000
            log.debug("loop tick %d: skipped (only %d executions)", self._tick, total)
            return tick

        # Compute error rate
        stats      = memory.global_stats()
        errors     = sum(s.fail_count for s in stats)
        error_rate = errors / total if total > 0 else 0.0
        tick.error_rate = error_rate

        # Decide action
        underperformers = memory.underperformers()
        evolution       = self._kernel._evolution

        if underperformers and error_rate > _ERROR_THRESHOLD and evolution:
            try:
                report = await evolution.evolve()
                tick.action         = "evolved"
                tick.evolved_agents = report.get("evolved", [])
                self._evolution_count += 1
                log.info(
                    "loop tick %d: evolved %s", self._tick, tick.evolved_agents
                )
            except Exception as exc:
                tick.action = "idle"
                log.debug("loop evolution failed: %s", exc)

        # Every 5 evolution cycles, suggest new features
        elif self._evolution_count > 0 and self._evolution_count % 5 == 0:
            autonomy = getattr(self._kernel, "_autonomy", None)
            if autonomy:
                try:
                    suggestions = await autonomy.suggest_improvements(n=1)
                    tick.action          = "suggested"
                    tick.new_suggestions = len(suggestions)
                except Exception as exc:
                    log.debug("loop suggest failed: %s", exc)

        else:
            tick.action = "idle"

        tick.duration_ms = (time.perf_counter() - t0) * 1000
        log.debug(
            "loop tick %d: %s error_rate=%.0f%% dt=%.0fms",
            self._tick, tick.action, error_rate * 100, tick.duration_ms,
        )
        return tick
