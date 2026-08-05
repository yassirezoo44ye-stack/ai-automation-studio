"""
Cost Guard — max_cost_usd/max_tokens budget on AgentPermissions, enforced
via live cancellation in EvolvableAgent.run() (app/agents/base.py), plus
the concrete report_usage() wiring into plan_agent.py/analyze_agent.py.

Matches tests/test_plugins.py's TestAgentRegistrationOwnership convention
for hand-constructing a minimal EvolvableAgent subclass.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent, RunBudget


def _ctx(**extra) -> AgentContext:
    return AgentContext(
        input="test", args="", kernel=MagicMock(), memory=MagicMock(), **extra,
    )


class _CostBoundedAgent(EvolvableAgent):
    """Loops reporting usage every iteration, yielding control each time
    so the budget-triggered cancellation actually gets a chance to land —
    this is what proves real cancellation, not just a post-hoc flag."""
    name        = "cost_bounded_test_agent"
    description = "test"
    group       = "test"

    def __init__(self, *, max_cost_usd=None, max_tokens=None, iterations=1000):
        self.iterations_run = 0
        self._max_iterations = iterations
        self._permissions = AgentPermissions(
            max_cost_usd=max_cost_usd, max_tokens=max_tokens, max_execution_seconds=5.0,
        )

    @property
    def permissions(self) -> AgentPermissions:
        return self._permissions

    async def execute(self, ctx: AgentContext) -> AgentResult:
        for _ in range(self._max_iterations):
            self.iterations_run += 1
            await ctx.report_usage(0.01, 100)
            await asyncio.sleep(0.005)
        return AgentResult.ok(self.name, f"completed {self.iterations_run} iterations")


class TestCostGuard(unittest.IsolatedAsyncioTestCase):
    async def test_exceeding_max_cost_usd_stops_the_agent(self):
        agent = _CostBoundedAgent(max_cost_usd=0.045)  # trips after ~5 iterations
        ctx = _ctx()
        result = await agent.run(ctx)

        self.assertFalse(result.success)
        self.assertIn("budget_exceeded", result.error)
        # Real cancellation, not a post-hoc flag: far fewer than the 1000
        # scheduled iterations actually ran.
        self.assertLess(agent.iterations_run, 50)
        self.assertGreaterEqual(agent.iterations_run, 1)

    async def test_exceeding_max_tokens_stops_the_agent(self):
        agent = _CostBoundedAgent(max_tokens=450)  # 100 tokens/iter -> trips ~iter 5
        ctx = _ctx()
        result = await agent.run(ctx)

        self.assertFalse(result.success)
        self.assertIn("budget_exceeded", result.error)
        self.assertLess(agent.iterations_run, 50)

    async def test_stopped_agent_does_not_keep_running_after_return(self):
        """The cancellation must be real — verify the loop doesn't
        silently continue in the background after run() has returned."""
        agent = _CostBoundedAgent(max_cost_usd=0.02)
        ctx = _ctx()
        await agent.run(ctx)
        count_at_return = agent.iterations_run
        await asyncio.sleep(0.05)
        self.assertEqual(agent.iterations_run, count_at_return)

    async def test_no_budget_set_runs_unbounded_by_default(self):
        """Control test: the default (max_cost_usd=None, max_tokens=None)
        must have zero effect — every existing agent is unaffected."""
        agent = _CostBoundedAgent(iterations=5)  # no max_cost_usd/max_tokens
        ctx = _ctx()
        result = await agent.run(ctx)

        self.assertTrue(result.success)
        self.assertEqual(agent.iterations_run, 5)

    async def test_wall_clock_timeout_still_works_independently_of_budget(self):
        """The pre-existing max_execution_seconds guard must still function
        when no budget is configured — this is the exact regression the
        base.py rewrite (asyncio.wait_for -> asyncio.wait) must not break."""
        class _SlowAgent(EvolvableAgent):
            name = "slow_test_agent"
            description = "test"
            group = "test"

            @property
            def permissions(self) -> AgentPermissions:
                return AgentPermissions(max_execution_seconds=0.05)

            async def execute(self, ctx: AgentContext) -> AgentResult:
                await asyncio.sleep(5.0)
                return AgentResult.ok(self.name, "should never get here")

        result = await _SlowAgent().run(_ctx())
        self.assertFalse(result.success)
        self.assertIn("max_execution_seconds", result.error)

    async def test_agent_context_report_usage_is_a_noop_without_budget(self):
        """A hand-constructed AgentContext with no .budget set (e.g. a
        test or ad hoc caller, not going through EvolvableAgent.run())
        must not raise when report_usage() is called."""
        ctx = _ctx()
        self.assertIsNone(ctx.budget)
        await ctx.report_usage(1.0, 1000)  # must not raise


class TestRunBudget(unittest.IsolatedAsyncioTestCase):
    async def test_record_sets_exceeded_only_past_threshold(self):
        b = RunBudget(max_cost_usd=0.10)
        b.record(0.05, 10)
        self.assertFalse(b.exceeded)
        b.record(0.06, 10)
        self.assertTrue(b.exceeded)

    async def test_unlimited_budget_never_trips(self):
        b = RunBudget()
        b.record(1_000_000.0, 1_000_000)
        self.assertFalse(b.exceeded)


if __name__ == "__main__":
    unittest.main()
