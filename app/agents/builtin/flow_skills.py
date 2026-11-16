"""AgentOS adapters for trusted Flow skills; advisory completions with no tools."""
from app.agents.base import (
    AgentContext, AgentPermissions, AgentResult, EvolvableAgent,
)
from app.ai.models import CompletionRequest, Message
from app.core.ai.inference.engine import InferenceEngine
from app.core.ai.skills import SKILL_IDS, compose_skill_system, load_skill
from app.core.db import get_pool


class FlowSkillAgent(EvolvableAgent):
    group = "flow_skills"

    def __init__(self, skill_id: str):
        super().__init__()
        skill = load_skill(skill_id)
        self.name = skill.id
        self.description = f"Advisory skill (no execution tools): {skill.description}"

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions(can_access_memory=False, max_execution_seconds=120)

    async def execute(self, ctx: AgentContext) -> AgentResult:
        if not ctx.user_id:
            return AgentResult.fail(self.name, "Authentication required for Flow skills")
        prompt = ctx.args.strip() or ctx.input.strip()
        system = compose_skill_system(
            "You are a Flow specialist. This invocation has no execution tools or "
            "access to project files, devices, accounts, or live data. Produce advice, "
            "drafts, or a plan from supplied information. Clearly identify missing "
            "sources and never claim you executed actions or inspected resources.",
            [self.name],
        )
        request = CompletionRequest(
            messages=[Message(role="user", content=prompt)],
            system=system, max_tokens=4096, timeout=100,
            memory_enabled=False, tools=None,
        )
        await ctx.step(f"Applying Flow skill: {self.name}", "info")
        response = await InferenceEngine(pool=get_pool()).complete(
            request, user_id=ctx.user_id, org_id=ctx.organization_id, auto_tools=False,
        )
        await ctx.report_usage(response.usage.cost_usd, response.usage.total_tokens)
        if response.tool_calls:
            return AgentResult.fail(self.name, "Skill requested unavailable tools",
                                    data={"skill_id": self.name, "mode": "advisory"})
        return AgentResult.ok(self.name, response.content or "", data={
            "skill_id": self.name, "mode": "advisory", "tools_enabled": False,
        })


def register(kernel):
    for skill_id in SKILL_IDS:
        kernel.register_agent(FlowSkillAgent(skill_id))
