"""Status agent — system overview: agents, memory, performance."""
from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, EvolvableAgent


class StatusAgent(EvolvableAgent):
    name        = "status"
    description = "Show system status: agents, memory, performance"
    group       = "system"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        kernel_status = ctx.kernel.status()
        memory_recent = ctx.memory.recent(5, org_id=ctx.organization_id)
        underperform  = ctx.memory.underperformers()

        lines = [
            f"Agents registered : {kernel_status['agents']}",
            f"Executions in memory: {kernel_status['memory_count']}",
            f"Underperformers   : {len(underperform)}",
            "",
            "Recent executions:",
        ]
        for rec in reversed(memory_recent):
            icon = "✓" if rec.success else "✗"
            lines.append(f"  {icon} {rec.agent:<12} {rec.input[:40]:<40} {rec.duration_ms:.0f}ms")

        if underperform:
            lines.append("")
            lines.append("Underperforming agents (run 'evolve run' to fix):")
            for s in underperform:
                lines.append(f"  ! {s.name:<12} {s.success_rate:.0%} success rate")

        return AgentResult.ok(
            self.name,
            "\n".join(lines),
            data=kernel_status,
        )

    def performance_hint(self) -> dict:
        return {"complexity": "low", "llm_needed": False}


agent = StatusAgent()
