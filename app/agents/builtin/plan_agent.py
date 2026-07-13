"""
Plan agent — task decomposition via LLM.

Converts a high-level goal into an ordered list of sub-tasks
that can be executed by other agents.

Usage:
  plan build and deploy my project
  plan optimize the build pipeline and fix slow agents
  plan <any natural language goal>
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)


class PlanAgent(EvolvableAgent):
    name        = "plan"
    description = "Decompose a high-level goal into executable sub-tasks"
    group       = "planning"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        goal = ctx.args.strip() if ctx.args else ctx.input.strip()

        if not goal or goal in ("plan",):
            return AgentResult.fail(
                self.name,
                "Specify a goal: plan <natural language goal>",
            )

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            # Fallback: simple rule-based decomposition
            tasks = _rule_based_plan(goal, list(ctx.kernel._agents.keys()))
            return AgentResult.ok(
                self.name,
                f"Plan ({len(tasks)} steps): {' → '.join(tasks)}",
                data={"goal": goal, "tasks": tasks, "method": "rule_based"},
            )

        tasks = await _llm_plan(goal, list(ctx.kernel._agents.keys()), api_key,
                                org_id=ctx.organization_id)
        return AgentResult.ok(
            self.name,
            f"Plan ({len(tasks)} steps): {' → '.join(tasks)}",
            data={"goal": goal, "tasks": tasks, "method": "llm"},
        )

    def performance_hint(self) -> dict:
        return {"complexity": "medium", "llm_needed": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _llm_plan(goal: str, agents: list[str], api_key: str, *,
                    org_id: Optional[str] = None) -> list[str]:
    from app.core.org_quota import check_org_quota_id, record_org_tokens
    if not await check_org_quota_id(org_id):
        return _rule_based_plan(goal, agents)
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Available agents: {', '.join(agents)}\n"
                    f"Goal: {goal}\n\n"
                    f"Decompose this goal into 2-5 sequential sub-tasks.\n"
                    f"Each task must start with an available agent name.\n"
                    f"Format: one task per line, no numbering, no explanations.\n"
                    f"Example:\n  analyze .\n  build .\n  deploy ."
                ),
            }],
        )
        try:
            total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
            await record_org_tokens(org_id, total_tokens, None, ref_type="agent_plan")
        except Exception:
            pass  # metering must never turn a successful reply into an error
        text  = msg.content[0].text.strip()
        tasks = [line.strip() for line in text.splitlines() if line.strip()]
        # Validate each task starts with a known agent
        valid = [t for t in tasks if t.split()[0] in agents]
        return valid if valid else _rule_based_plan(goal, agents)
    except Exception as exc:
        log.debug("plan llm failed: %s", exc)
        return _rule_based_plan(goal, agents)


def _rule_based_plan(goal: str, agents: list[str]) -> list[str]:
    """Simple keyword-based plan when LLM unavailable."""
    g = goal.lower()
    tasks: list[str] = []

    if "analyz" in g or "inspect" in g or "check" in g:
        tasks.append("analyze .")
    if "build" in g or "compil" in g or "bundl" in g:
        tasks.append("build .")
    if "deploy" in g or "release" in g or "ship" in g:
        tasks.append("deploy .")
    if "evolv" in g or "optim" in g or "improv" in g:
        tasks.append("evolve run")
    if "run" in g or "start" in g or "serve" in g:
        tasks.append("run .")

    return tasks or ["analyze .", "build .", "deploy ."]


agent = PlanAgent()
