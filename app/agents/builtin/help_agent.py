"""Help agent — lists all agents and their descriptions."""
from __future__ import annotations

from app.agents.base import AgentContext, AgentResult, EvolvableAgent


class HelpAgent(EvolvableAgent):
    name        = "help"
    description = "List all registered agents and usage"
    group       = "system"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        all_agents = ctx.kernel.all_agents()
        by_group: dict[str, list] = {}
        for ag in sorted(all_agents, key=lambda a: (a.group, a.name)):
            by_group.setdefault(ag.group, []).append(ag)

        lines = ["Agentic OS — registered agents", ""]
        for group, agents in sorted(by_group.items()):
            lines.append(f"[{group}]")
            for ag in agents:
                lines.append(f"  {ag.name:<14} {ag.description}")
            lines.append("")

        lines.append("Usage: <agent-name> [args]")
        lines.append("       collaborate <task1> | <task2> | <task3>")
        lines.append("       plan <high-level goal>")

        return AgentResult.ok(
            self.name,
            "\n".join(lines),
            data={
                "agents": [ag.to_dict() for ag in all_agents],
                "count" : len(all_agents),
            },
        )

    def performance_hint(self) -> dict:
        return {"complexity": "low"}


agent = HelpAgent()
