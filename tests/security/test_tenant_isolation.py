"""
Security Regression Suite — Tenant Isolation.

Cross-org data-visibility fixes: organization A must never see, invoke,
or be able to reference organization B's agents, suggestions, or running
tasks. Distinct from test_memory_isolation.py (AgentMemory/LayeredMemory
raw content specifically) — this file covers the agent kernel's
execution-time ownership gate and the AutonomyEngine's org-scoped state.

Relocated (unmodified) from tests/test_security_hardening.py and
tests/test_agent_os.py as part of the Security Testing phase's
tests/security/ reorganization. No behavioral change.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.base import AgentContext, AgentResult, EvolvableAgent
from app.agents.intent import IntentParser
from app.agents.memory import AgentMemory, ExecutionRecord


# ── Shared helpers (mirrors tests/test_agent_os.py's construction pattern) ──────

class EchoAgent(EvolvableAgent):
    name        = "echo"
    description = "Echoes args back"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, ctx.args or "empty", data={"args": ctx.args})


class SlowAgent(EvolvableAgent):
    name        = "slow"
    description = "Takes 50ms"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        await asyncio.sleep(0.05)
        return AgentResult.ok(self.name, "done")


class _OwnedAgent(EvolvableAgent):
    name        = "owned_agent"
    description = "belongs to whichever org registered it"
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, f"ran for org={ctx.organization_id}")


def _make_memory() -> AgentMemory:
    """In-memory only (no file I/O)."""
    import threading
    mem = AgentMemory.__new__(AgentMemory)
    mem._lock    = threading.Lock()
    mem._records = []
    return mem


def _make_kernel():
    from app.agents.kernel import AgentKernel
    from app.plugins.registry_guard import OwnershipTracker
    k = AgentKernel.__new__(AgentKernel)
    k._agents       = {}
    k._agent_owners = OwnershipTracker("agent")
    k._memory       = _make_memory()
    k._parser       = IntentParser()
    k._booted       = True
    k._modifier     = None
    k._reloader     = None
    k._evolution    = None
    k._router       = None
    k._reflector    = None
    k._deliberation = None
    k._autonomy     = None
    k._loop         = None
    return k


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-tenant agent listing (app/agents/kernel.py, agent_os_api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentosAgentEndpointsAreOrgScoped(unittest.TestCase):
    """GET /api/agentos/agents and /status used to return every org's
    plugin-installed/self-generated agent names + metadata with zero
    tenant scoping — /agents took no request context at all. Now scoped
    via AgentKernel.visible_agents()/status(organization_id=...), the
    Agent Execution Isolation phase's core fix."""

    def _kernel_with_two_tenants(self):
        import threading
        from app.agents.base import AgentResult, EvolvableAgent
        from app.agents.intent import IntentParser
        from app.agents.kernel import AgentKernel
        from app.agents.memory import AgentMemory
        from app.plugins.registry_guard import OwnershipTracker

        class _OrgAgent(EvolvableAgent):
            group = "test"
            def __init__(self, name):
                self.name = name
                self.description = "owned"
            async def execute(self, ctx: AgentContext) -> AgentResult:
                return AgentResult.ok(self.name, "ok")

        mem = AgentMemory.__new__(AgentMemory)
        mem._lock, mem._records = threading.Lock(), []

        kernel = AgentKernel.__new__(AgentKernel)
        kernel._agents, kernel._memory = {}, mem
        kernel._agent_owners = OwnershipTracker("agent")
        kernel._parser = IntentParser()
        kernel._booted = True
        kernel._modifier = kernel._reloader = kernel._router = None
        kernel._reflector = kernel._deliberation = kernel._autonomy = kernel._loop = None
        kernel._evolution = None

        kernel.register_agent(_OrgAgent("shared_builtin"))               # owner=None
        kernel.register_agent(_OrgAgent("org_a_secret_agent"), owner="org-a")
        kernel.register_agent(_OrgAgent("org_b_secret_agent"), owner="org-b")
        kernel._parser.update_agents(list(kernel._agents.keys()))
        return kernel

    def test_agents_endpoint_hides_other_orgs_custom_agents(self):
        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-a")), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_agents
                return await agentos_agents(MagicMock())

        result = asyncio.run(_run())
        names = {a["name"] for a in result["agents"]}
        self.assertIn("shared_builtin", names)
        self.assertIn("org_a_secret_agent", names)
        self.assertNotIn("org_b_secret_agent", names)

    def test_agents_endpoint_with_no_verified_org_sees_only_builtins(self):
        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value=None)), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_agents
                return await agentos_agents(MagicMock())

        result = asyncio.run(_run())
        names = {a["name"] for a in result["agents"]}
        self.assertEqual(names, {"shared_builtin"})

    def test_status_endpoint_agent_names_scoped_to_caller_org(self):
        kernel = self._kernel_with_two_tenants()

        async def _run():
            with patch("app.tenancy.context.optional_org_id", new=AsyncMock(return_value="org-b")), \
                 patch("app.agents.kernel.get_agent_kernel", return_value=kernel):
                from app.routers.agent_os_api import agentos_status
                return await agentos_status(MagicMock())

        result = asyncio.run(_run())
        self.assertIn("org_b_secret_agent", result["agent_names"])
        self.assertNotIn("org_a_secret_agent", result["agent_names"])


# ═══════════════════════════════════════════════════════════════════════════════
# Agent execution isolation (app/agents/kernel.py) — the execution-time gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentExecutionIsolation:
    def setup_method(self):
        self.kernel = _make_kernel()
        self.kernel.register_agent(EchoAgent())          # owner=None: built-in
        self.kernel.register_agent(SlowAgent())           # owner=None: built-in
        self.kernel.register_agent(_OwnedAgent(), owner="org-a")
        self.kernel._parser.update_agents(list(self.kernel._agents.keys()))

    def test_owner_can_invoke_its_own_agent(self):
        result = _run(self.kernel.run("owned_agent", organization_id="org-a"))
        assert result.success
        assert "org=org-a" in result.output

    def test_other_org_cannot_invoke_it_by_name(self):
        # Org B running a tool/agent against a resource belonging to org A:
        # intent-parsing still resolves the real registered name, but the
        # execution gate must treat it exactly like "no agent for this
        # intent" — same error shape as a genuinely unknown name, so org B
        # gets no signal that org-a's agent even exists.
        result = _run(self.kernel.run("owned_agent", organization_id="org-b"))
        assert result.success is False
        assert result.error == "agent_not_found"
        assert "owned_agent" not in result.data.get("agents", [])

    def test_forged_or_missing_org_id_is_not_a_wildcard(self):
        # optional_org_id() never raises — an unauthenticated caller or one
        # with a garbage header value still reaches kernel.run() with some
        # organization_id. Neither None nor a made-up value may act as a
        # skeleton key that unlocks every tenant's agents.
        for org in (None, "totally-made-up-org", ""):
            result = _run(self.kernel.run("owned_agent", organization_id=org))
            assert result.success is False
            assert result.error == "agent_not_found"

    def test_builtin_stays_invocable_by_everyone(self):
        for org in (None, "org-a", "org-b", "anything"):
            result = _run(self.kernel.run("echo hi", organization_id=org))
            assert result.success

    def test_visible_agent_names_scoped_per_org(self):
        assert "owned_agent" in self.kernel.visible_agent_names("org-a")
        assert "owned_agent" not in self.kernel.visible_agent_names("org-b")
        assert "owned_agent" not in self.kernel.visible_agent_names(None)
        assert "echo" in self.kernel.visible_agent_names("org-b")  # built-in

    def test_status_agent_names_scoped_per_org(self):
        s_a = self.kernel.status(organization_id="org-a")
        s_b = self.kernel.status(organization_id="org-b")
        assert "owned_agent" in s_a["agent_names"]
        assert "owned_agent" not in s_b["agent_names"]

    def test_concurrent_execution_from_two_orgs_stays_isolated(self):
        # Two orgs hitting the kernel at the same time via asyncio.gather —
        # org-b's call must fail exactly as it would alone, unaffected by
        # org-a's concurrent, legitimate call to the same agent name.
        async def scenario():
            return await asyncio.gather(
                self.kernel.run("owned_agent", organization_id="org-a"),
                self.kernel.run("owned_agent", organization_id="org-b"),
            )

        a_result, b_result = _run(scenario())
        assert a_result.success is True
        assert b_result.success is False
        assert b_result.error == "agent_not_found"

    def test_cancelling_one_orgs_task_does_not_cancel_anothers(self):
        async def scenario():
            t_a = asyncio.ensure_future(self.kernel.run("slow", organization_id="org-a"))
            t_b = asyncio.ensure_future(self.kernel.run("echo still-fine", organization_id="org-b"))
            await asyncio.sleep(0.01)
            t_a.cancel()
            b_result = await t_b
            try:
                await t_a
            except asyncio.CancelledError:
                pass
            return b_result

        b_result = _run(scenario())
        assert b_result.success
        assert "still-fine" in b_result.output

    def test_deliberation_only_bids_from_visible_agents(self):
        # Deliberation.vote() used to call kernel.all_agents() — another
        # org's agent could bid on (and win) a request it should never
        # even see, let alone execute.
        from app.agents.deliberation import Deliberation
        delib = Deliberation()
        result = _run(delib.vote("owned_agent", self.kernel, org_id="org-b"))
        assert result.winner != "owned_agent"


# ═══════════════════════════════════════════════════════════════════════════════
# StatusAgent — the other raw-content reader that used to leak cross-tenant
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatusAgentOrgScoping:
    def test_status_agent_only_sees_own_org_executions(self):
        # Same agent name ("echo") on both records on purpose — isolation
        # must hold on organization_id alone, not accidentally depend on
        # agent name/id ever differing between tenants.
        from app.agents.builtin.status_agent import StatusAgent

        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="echo", input="org-a confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
            ExecutionRecord(agent="echo", input="org-b confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-b"),
        ]
        kernel = _make_kernel()
        kernel._memory = mem
        ctx = AgentContext(input="status", args="", kernel=kernel, memory=mem,
                           organization_id="org-a")

        result = _run(StatusAgent().execute(ctx))

        assert "org-a confidential task" in result.output
        assert "org-b confidential task" not in result.output

    def test_status_agent_with_no_org_sees_only_no_org_bucket(self):
        # A caller with no verified org (organization_id=None) must be
        # scoped to the no-org bucket, never fall through to "everyone's
        # data" — this is the exact bug caught before the fix landed.
        from app.agents.builtin.status_agent import StatusAgent

        mem = _make_memory()
        mem._records += [
            ExecutionRecord(agent="echo", input="org-a confidential task", args="",
                             success=True, duration_ms=1.0, organization_id="org-a"),
        ]
        kernel = _make_kernel()
        kernel._memory = mem
        ctx = AgentContext(input="status", args="", kernel=kernel, memory=mem,
                           organization_id=None)

        result = _run(StatusAgent().execute(ctx))

        assert "org-a confidential task" not in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# AutonomyEngine — self._suggestions is a single kernel-wide list shared by
# every org's suggest_improvements() calls; generate_agent() writes into the
# same app/agents/builtin/ directory used by real built-ins.
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomyEngineOrgScoping:
    def _engine(self, api_key="fake-key-for-test"):
        from app.agents.autonomy import AutonomyEngine
        engine = AutonomyEngine.__new__(AutonomyEngine)
        engine._kernel      = None
        engine._suggestions = []
        engine._api_key     = api_key
        return engine

    def test_generate_agent_without_org_id_is_rejected_before_any_write(self):
        # Guards against the pre-fix behavior: a caller with no verified
        # org membership had its generated agent registered as owner=None
        # (a protected built-in, invocable by every tenant). Checked before
        # any file I/O or LLM call — engine._kernel is None here on purpose,
        # so a bug that reached that code would crash the test loudly.
        engine = self._engine()
        result = _run(engine.generate_agent("does anything", org_id=None))
        assert result["status"] == "error"
        assert "organization" in result["error"]

    def test_generate_agent_with_no_api_key_fails_before_org_check(self):
        # Existing precedence preserved: missing API key is still reported
        # as its own distinct error, not masked by the new org check.
        engine = self._engine(api_key="")
        result = _run(engine.generate_agent("does anything", org_id="org-a"))
        assert result["status"] == "error"
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_implement_suggestion_blocks_cross_org_index_reference(self):
        # self._suggestions is shared kernel-wide — index alone must not be
        # enough to implement (and consume) another org's suggestion.
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [Suggestion(
            index=0, title="t", description="d", agent_name="x", file="f",
            priority=0.5, organization_id="org-a",
        )]
        result = _run(engine.implement_suggestion(0, org_id="org-b"))
        assert result["status"] == "error"
        assert "No suggestion" in result["error"]

    def test_owner_can_reference_its_own_suggestion_index(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine(api_key="")   # force the API-key error path,
        engine._suggestions = [Suggestion(  # so this stays a safe no-write test
            index=0, title="t", description="d", agent_name="x", file="f",
            priority=0.5, organization_id="org-a",
        )]
        result = _run(engine.implement_suggestion(0, org_id="org-a"))
        # Reaches generate_agent() (proving the org match found the
        # suggestion) and fails there on the missing API key, not on
        # "No suggestion at index".
        assert result["status"] == "error"
        assert "ANTHROPIC_API_KEY" in result["error"]

    def test_all_suggestions_scoped_to_org(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [
            Suggestion(index=0, title="a", description="d", agent_name="a",
                      file="f", priority=0.5, organization_id="org-a"),
            Suggestion(index=1, title="b", description="d", agent_name="b",
                      file="f", priority=0.5, organization_id="org-b"),
        ]
        org_a_view = engine.all_suggestions(org_id="org-a")
        assert len(org_a_view) == 1
        assert org_a_view[0]["agent_name"] == "a"

    def test_pending_suggestions_scoped_to_org(self):
        from app.agents.autonomy import Suggestion
        engine = self._engine()
        engine._suggestions = [
            Suggestion(index=0, title="a", description="d", agent_name="a",
                      file="f", priority=0.5, organization_id="org-a"),
            Suggestion(index=1, title="b", description="d", agent_name="b",
                      file="f", priority=0.5, organization_id="org-b"),
        ]
        pending = engine.pending_suggestions(org_id="org-a")
        assert [s.agent_name for s in pending] == ["a"]


if __name__ == "__main__":
    unittest.main()
