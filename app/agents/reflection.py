"""
Self-Reflection Engine — each execution triggers a reflection cycle.

After every AgentKernel.run() completes, the reflector:
  1. Records the execution with success/failure context
  2. Identifies patterns in recent failures
  3. Writes a ReflectionRecord to persistent memory
  4. If error_rate > threshold: flags agents for evolution
  5. Optionally: uses LLM to suggest improvements (async, non-blocking)

The reflector runs asynchronously so it never slows down the main execution path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from app.agents.base   import AgentResult
from app.agents.memory import AgentMemory

log = logging.getLogger(__name__)

_REFLECTION_FILE = Path(tempfile.gettempdir()) / "agent-reflections.json"
_REFLECT_EVERY   = 10    # reflect after every N executions
_ERROR_THRESHOLD = 0.30  # flag for evolution when error rate exceeds this


@dataclass
class ReflectionRecord:
    timestamp     : float = field(default_factory=time.time)
    execution_count: int  = 0
    error_rate    : float = 0.0
    flagged_agents: list[str] = field(default_factory=list)
    insight       : str   = ""
    action_taken  : str   = "none"   # none | flagged | evolved | suggested

    def to_dict(self) -> dict:
        return asdict(self)


class SelfReflector:
    """
    Non-blocking self-reflection after each execution.

    Call reflect(result, memory) after every kernel.run() — it schedules
    an async reflection task without awaiting, so the caller is not blocked.
    """

    def __init__(self) -> None:
        self._count      : int = 0
        self._reflections: list[ReflectionRecord] = []
        self._load()

    # ── Public ────────────────────────────────────────────────────────────────

    def reflect(self, result: AgentResult, memory: AgentMemory,
                evolution_engine=None) -> None:
        """Fire-and-forget: schedule reflection without blocking."""
        self._count += 1
        if self._count % _REFLECT_EVERY != 0:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._reflect_async(result, memory, evolution_engine)
                )
        except RuntimeError:
            pass   # no event loop — skip async reflection

    async def reflect_async(self, result: AgentResult, memory: AgentMemory,
                            evolution_engine=None) -> ReflectionRecord:
        """Awaitable version — use when you want the reflection result."""
        return await self._reflect_async(result, memory, evolution_engine)

    def recent(self, n: int = 10) -> list[ReflectionRecord]:
        return list(self._reflections[-n:])

    def to_dict_list(self) -> list[dict]:
        return [r.to_dict() for r in self._reflections[-20:]]

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _reflect_async(self, result: AgentResult, memory: AgentMemory,
                             evolution_engine=None) -> ReflectionRecord:
        stats      = memory.global_stats()
        total      = memory.total_count()
        errors     = sum(s.fail_count for s in stats)
        error_rate = errors / total if total > 0 else 0.0
        flagged    = [s.name for s in memory.underperformers()]

        rec = ReflectionRecord(
            execution_count = total,
            error_rate      = round(error_rate, 3),
            flagged_agents  = flagged,
        )

        # Generate LLM insight if available
        rec.insight = await self._llm_insight(result, error_rate, flagged)

        # Auto-trigger evolution if threshold exceeded and engine available
        if flagged and error_rate > _ERROR_THRESHOLD and evolution_engine:
            try:
                report = await evolution_engine.evolve()
                rec.action_taken = "evolved"
                rec.insight += f" Auto-evolved: {report.get('evolved', [])}"
            except Exception as exc:
                log.debug("auto-evolution failed: %s", exc)
                rec.action_taken = "flagged"
        elif flagged:
            rec.action_taken = "flagged"

        self._reflections.append(rec)
        if len(self._reflections) > 100:
            self._reflections = self._reflections[-100:]
        self._persist()

        log.info(
            "reflection: total=%d error_rate=%.0f%% flagged=%s action=%s",
            total, error_rate * 100, flagged, rec.action_taken,
        )
        return rec

    async def _llm_insight(self, result: AgentResult, error_rate: float,
                           flagged: list[str]) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return ""
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=128,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Agentic OS reflection:\n"
                        f"Error rate: {error_rate:.0%}\n"
                        f"Underperforming agents: {', '.join(flagged) or 'none'}\n"
                        f"Last result: {result.agent} {'✓' if result.success else '✗'} {result.error or ''}\n"
                        f"Give one actionable suggestion in under 20 words."
                    ),
                }],
            )
            return msg.content[0].text.strip()
        except Exception:
            return ""

    def _persist(self) -> None:
        try:
            tmp = _REFLECTION_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps([r.to_dict() for r in self._reflections]),
                encoding="utf-8",
            )
            tmp.replace(_REFLECTION_FILE)
        except Exception as exc:
            log.debug("reflection persist failed: %s", exc)

    def _load(self) -> None:
        if not _REFLECTION_FILE.exists():
            return
        try:
            data = json.loads(_REFLECTION_FILE.read_text(encoding="utf-8"))
            self._reflections = [ReflectionRecord(**d) for d in data]
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_reflector: SelfReflector | None = None


def get_reflector() -> SelfReflector:
    global _reflector
    if _reflector is None:
        _reflector = SelfReflector()
    return _reflector
