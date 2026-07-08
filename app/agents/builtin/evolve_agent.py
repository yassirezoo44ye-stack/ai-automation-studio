"""Evolve agent — triggers the self-evolution cycle."""
from __future__ import annotations

import logging

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)


class EvolveAgent(EvolvableAgent):
    name        = "evolve"
    description = "Analyze agent performance and auto-improve underperformers via LLM"
    group       = "system"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        sub = ctx.args.strip().lower() if ctx.args else ""

        evolution = ctx.kernel._evolution
        if evolution is None:
            return AgentResult.fail(self.name, "Evolution engine not initialized")

        if sub in ("analyze", "check", "report", "dry-run", "dryrun", ""):
            # Analyze only — no changes
            report = evolution.analyze()
            candidates = [c.name for c in report.candidates]
            if not candidates:
                return AgentResult.ok(
                    self.name, "All agents performing well — no evolution needed",
                    data=report.to_dict(),
                )
            return AgentResult.ok(
                self.name,
                f"{len(candidates)} agent(s) are candidates for evolution: {', '.join(candidates)}",
                data=report.to_dict(),
            )

        if sub in ("run", "go", "execute", "start"):
            report = await ctx.kernel.evolve()
            evolved = report.get("evolved", [])
            if not evolved:
                return AgentResult.ok(
                    self.name, "Evolution cycle complete — no changes needed",
                    data=report,
                )
            return AgentResult.ok(
                self.name,
                f"Evolved {len(evolved)} agent(s): {', '.join(evolved)}",
                data=report,
            )

        if sub == "last":
            last = evolution.last_report()
            if last is None:
                return AgentResult.ok(self.name, "No evolution cycle has run yet",
                                      data={"status": "never_run"})
            return AgentResult.ok(self.name, f"Last evolution: {last.status}",
                                  data=last.to_dict())

        return AgentResult.fail(
            self.name,
            "Usage: evolve [analyze|run|last]",
            data={"subcommands": ["analyze (default)", "run", "last"]},
        )

    def performance_hint(self) -> dict:
        return {"complexity": "high", "llm_needed": True, "timeout_s": 120}


agent = EvolveAgent()
