"""
Security Regression Suite — Tool Authorization.

The Tool Dispatcher (app/core/ai/tools/executor.py) is the hard boundary
between "the model asked for a tool" and "a tool actually ran" — a
returned tool_call naming anything outside the caller's offered tool set
(hallucinated, prompt-injected, or a real but unauthorized tool) must be
rejected before the underlying function ever executes. Enforced at two
layers: ToolExecutor.execute()'s allowed_tools set, and AgentRuntime's
tool loop re-checking every tool_call against AgentConfig.tools.

Relocated (unmodified) from tests/test_ai_platform.py as part of the
Security Testing phase's tests/security/ reorganization. No behavioral
change.
"""
from __future__ import annotations

import pytest

from app.core.ai.tools.executor import ToolExecutor


class TestToolExecutorAllowedTools:
    def _register_probe_tool(self, name: str):
        from app.ai.models import ToolSchema
        from app.ai.tools import register_tool
        calls: list[dict] = []

        async def fn(**kwargs):
            calls.append(kwargs)
            return "ran"

        register_tool(
            ToolSchema(name=name, description="d", parameters={"type": "object", "properties": {}}),
            fn, owner=None,
        )
        return calls

    @pytest.mark.asyncio
    async def test_tool_not_in_allowed_set_is_rejected_without_running(self):
        from app.ai.tools import unregister_tool
        import uuid
        name = f"probe_{uuid.uuid4().hex[:8]}"
        calls = self._register_probe_tool(name)
        try:
            executor = ToolExecutor()
            result = await executor.execute(name, {}, allowed_tools={"some_other_tool"})
            assert result.success is False
            assert "not among the tools available" in (result.error or "")
            assert calls == []   # the underlying fn must never have run
        finally:
            unregister_tool(name)

    @pytest.mark.asyncio
    async def test_tool_in_allowed_set_runs_normally(self):
        from app.ai.tools import unregister_tool
        import uuid
        name = f"probe_{uuid.uuid4().hex[:8]}"
        calls = self._register_probe_tool(name)
        try:
            executor = ToolExecutor()
            result = await executor.execute(name, {}, allowed_tools={name})
            assert result.success is True
            assert len(calls) == 1
        finally:
            unregister_tool(name)

    @pytest.mark.asyncio
    async def test_allowed_tools_none_preserves_prior_unrestricted_behavior(self):
        # Backward compat: a caller that doesn't pass allowed_tools at all
        # (the default) isn't newly broken by this change.
        from app.ai.tools import unregister_tool
        import uuid
        name = f"probe_{uuid.uuid4().hex[:8]}"
        calls = self._register_probe_tool(name)
        try:
            executor = ToolExecutor()
            result = await executor.execute(name, {})
            assert result.success is True
            assert len(calls) == 1
        finally:
            unregister_tool(name)

    @pytest.mark.asyncio
    async def test_empty_allowed_tools_rejects_everything(self):
        # An agent/request offered NO tools must not be able to run any —
        # empty set is a real, restrictive value, not "unset".
        from app.ai.tools import unregister_tool
        import uuid
        name = f"probe_{uuid.uuid4().hex[:8]}"
        calls = self._register_probe_tool(name)
        try:
            executor = ToolExecutor()
            result = await executor.execute(name, {}, allowed_tools=set())
            assert result.success is False
            assert calls == []
        finally:
            unregister_tool(name)


class TestAgentRuntimeToolAllowlist:
    """Agent Execution Isolation carried one layer further: AgentConfig.tools
    was only ever advisory (shaped the provider request) — nothing
    previously stopped a returned tool_call naming a tool outside it."""

    @pytest.mark.asyncio
    async def test_agent_run_rejects_tool_call_outside_config_tools(self):
        from app.ai.models import ToolSchema
        from app.ai.tools import register_tool, unregister_tool
        from app.core.ai.agents.runtime import AgentConfig, AgentRuntime
        from app.ai.models import CompletionResponse, ToolCall
        import uuid

        # Registered and real (e.g. another org's plugin tool, or an
        # admin-only one) — but NOT in this agent's own config.tools.
        other_tool_name = f"other_tool_{uuid.uuid4().hex[:8]}"
        calls: list[dict] = []

        async def other_fn(**kw):
            calls.append(kw)
            return "ran"

        register_tool(
            ToolSchema(name=other_tool_name, description="d", parameters={"type": "object", "properties": {}}),
            other_fn, owner=None,
        )

        try:
            config = AgentConfig(name="probe", tools=["allowed_tool"], max_rounds=2)
            agent  = AgentRuntime(config=config)

            first_resp = CompletionResponse(
                content="", tool_calls=[ToolCall(id="1", name=other_tool_name, arguments={})],
            )
            final_resp = CompletionResponse(content="done", tool_calls=[])

            async def fake_complete_with_events(req, request_id=""):
                if req.messages and req.messages[-1].role == "tool":
                    return final_resp, "anthropic"
                return first_resp, "anthropic"

            import app.core.ai.registry.registry as registry_mod
            original = registry_mod.platform_registry.complete_with_events
            registry_mod.platform_registry.complete_with_events = fake_complete_with_events
            try:
                result = await agent.run("do something")
            finally:
                registry_mod.platform_registry.complete_with_events = original

            assert result.success is True
            assert result.tool_calls[0]["name"] == other_tool_name
            # The registered tool's own function must never have run,
            # even though it's a real, resolvable name in _REGISTRY.
            assert calls == []
        finally:
            unregister_tool(other_tool_name)


if __name__ == "__main__":
    pytest.main([__file__])
