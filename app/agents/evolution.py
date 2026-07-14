"""
Self-Evolution Engine — the heart of the Agentic OS.

Analyzes agent performance from memory, identifies underperformers,
and rewrites their source code using Claude (LLM-in-the-loop).

Flow:
  1. analyzeUsage()  — reads AgentMemory, builds PerformanceReport
  2. evolve()        — for each underperformer, call _rewrite_agent()
  3. _rewrite_agent()— sends current source + performance data to Claude,
                       applies patch via SelfModifyingEngine, hot-reloads

Safety:
  - Every rewrite is backed up (via SelfModifyingEngine.patch / .replace)
  - Policy engine blocks modification of protected files
  - Rollback available via kernel rollback command
  - Max 1 evolve cycle per 60s (cooldown)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.agents.memory import AgentMemory
    from app.kernel.self_modify import SelfModifyingEngine
    from app.kernel.reloader import HotReloader

log = logging.getLogger(__name__)

_COOLDOWN_S = 60.0          # minimum seconds between evolution cycles
_MIN_CALLS  = 5             # ignore agents with fewer executions
_THRESHOLD  = 0.70          # success rate below this → candidate for evolution

_AGENTS_DIR = Path(__file__).parent / "builtin"


@dataclass
class EvolutionCandidate:
    name        : str
    file        : str           # relative path for SelfModifyingEngine
    success_rate: float
    call_count  : int
    avg_ms      : float
    error_sample: list[str] = field(default_factory=list)


@dataclass
class EvolutionReport:
    timestamp   : float = field(default_factory=time.time)
    candidates  : list[EvolutionCandidate] = field(default_factory=list)
    evolved     : list[str] = field(default_factory=list)
    skipped     : list[str] = field(default_factory=list)
    errors      : list[str] = field(default_factory=list)
    status      : str = "idle"      # idle | stable | evolved | error

    def to_dict(self) -> dict:
        return {
            "timestamp" : self.timestamp,
            "status"    : self.status,
            "candidates": [
                {"name": c.name, "success_rate": c.success_rate,
                 "call_count": c.call_count, "avg_ms": c.avg_ms}
                for c in self.candidates
            ],
            "evolved"   : self.evolved,
            "skipped"   : self.skipped,
            "errors"    : self.errors,
        }


class EvolutionEngine:
    """
    LLM-driven self-evolution.  Requires ANTHROPIC_API_KEY in environment.

    Usage:
        engine = EvolutionEngine(memory, modifier, reloader)
        report = await engine.evolve()
    """

    def __init__(
        self,
        memory  : "AgentMemory",
        modifier: "SelfModifyingEngine",
        reloader: "HotReloader",
    ) -> None:
        self._memory   = memory
        self._modifier = modifier
        self._reloader = reloader
        self._last_run : float = 0.0
        self._last_report: Optional[EvolutionReport] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def analyze(self) -> EvolutionReport:
        """Build a performance report without making any changes."""
        underperformers = self._memory.underperformers(
            threshold=_THRESHOLD, min_calls=_MIN_CALLS
        )
        candidates = []
        for stats in underperformers:
            file = _agent_file(stats.name)
            if file is None:
                continue
            errors = [
                r.error for r in self._memory.for_agent(stats.name)
                if r.error
            ][-10:]
            candidates.append(EvolutionCandidate(
                name         = stats.name,
                file         = file,
                success_rate = stats.success_rate,
                call_count   = stats.call_count,
                avg_ms       = stats.avg_ms,
                error_sample = errors,
            ))

        report = EvolutionReport(candidates=candidates)
        report.status = "stable" if not candidates else "pending"
        return report

    async def evolve(self, *, org_id: Optional[str] = None) -> EvolutionReport:
        """
        Analyze + rewrite underperforming agents using Claude.
        Respects cooldown to prevent runaway self-modification.
        """
        elapsed = time.time() - self._last_run
        if elapsed < _COOLDOWN_S:
            return EvolutionReport(
                status="cooldown",
                errors=[f"Evolution on cooldown — {_COOLDOWN_S - elapsed:.0f}s remaining"],
            )

        self._last_run = time.time()
        report = self.analyze()

        if not report.candidates:
            report.status = "stable"
            self._last_report = report
            return report

        for candidate in report.candidates:
            try:
                evolved = await self._rewrite_agent(candidate, org_id=org_id)
                if evolved:
                    report.evolved.append(candidate.name)
                else:
                    report.skipped.append(candidate.name)
            except Exception as exc:
                log.error("evolution failed for %s: %s", candidate.name, exc)
                report.errors.append(f"{candidate.name}: {exc}")

        report.status = "evolved" if report.evolved else "stable"
        self._last_report = report
        return report

    def last_report(self) -> Optional[EvolutionReport]:
        return self._last_report

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _rewrite_agent(self, candidate: EvolutionCandidate, *,
                             org_id: Optional[str] = None) -> bool:
        """
        Ask Claude to improve the agent source, then apply the patch.
        Returns True if the file was actually modified.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.warning("ANTHROPIC_API_KEY not set — skipping LLM evolution for %s",
                        candidate.name)
            return False

        from app.core.org_quota import check_org_quota_id, record_org_tokens
        if not await check_org_quota_id(org_id):
            log.warning("org %s over quota — skipping evolution rewrite for %s",
                        org_id, candidate.name)
            return False

        # Read current source
        file_path = Path(__file__).parent.parent.parent / candidate.file
        if not file_path.exists():
            log.warning("agent file not found: %s", candidate.file)
            return False

        source = file_path.read_text(encoding="utf-8")

        # Build improvement prompt
        errors_text = "\n".join(f"  - {e}" for e in candidate.error_sample) or "  (none recorded)"
        prompt = f"""You are improving a Python agent in an Agentic OS runtime.

Agent: {candidate.name}
Performance: {candidate.success_rate:.0%} success rate over {candidate.call_count} calls
Average duration: {candidate.avg_ms:.0f}ms
Recent errors:
{errors_text}

Current source:
```python
{source}
```

Task: Improve the agent to fix common errors and increase reliability.
Rules:
1. Keep the same class name, `name`, `description`, `group` attributes
2. Keep the `execute(self, ctx: AgentContext) -> AgentResult` signature
3. Add better error handling around the most likely failure points
4. If errors mention a specific issue, fix that specific issue
5. Do NOT change imports unless adding a missing one
6. Return ONLY the complete improved Python source, no explanation
"""

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
                await record_org_tokens(org_id, total_tokens, None, ref_type="agent_evolution")
            except Exception:
                pass  # metering must never turn a successful reply into an error
            new_source = msg.content[0].text.strip()

            # Strip markdown fences if Claude wrapped the code
            if new_source.startswith("```"):
                lines = new_source.split("\n")
                new_source = "\n".join(
                    line for line in lines
                    if not line.startswith("```")
                )

            if new_source == source:
                log.info("evolution: no changes for %s", candidate.name)
                return False

            # Apply via SelfModifyingEngine (creates backup, checks policy)
            self._modifier.replace(
                candidate.file,
                content=new_source,
                description=f"auto-evolved: {candidate.success_rate:.0%} → improve reliability",
            )

            # Hot-reload the module
            try:
                self._reloader.reload_plugin(file_path)
            except Exception as exc:
                log.warning("hot-reload after evolution failed: %s", exc)

            log.info("agent evolved: %s", candidate.name)
            return True

        except Exception as exc:
            log.error("LLM rewrite failed for %s: %s", candidate.name, exc)
            raise


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agent_file(agent_name: str) -> Optional[str]:
    """Map agent name to relative file path for SelfModifyingEngine."""
    candidates = [
        f"app/agents/builtin/{agent_name}_agent.py",
        f"app/agents/builtin/{agent_name}.py",
        f"agents/{agent_name}.py",
    ]
    root = Path(__file__).parent.parent.parent
    for rel in candidates:
        if (root / rel).exists():
            return rel
    return None
