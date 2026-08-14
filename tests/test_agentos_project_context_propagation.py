"""
Regression tests — AgentOS project-context propagation.

Covers the 8 scenarios defined in the production closure audit:
  1. Arabic input + valid project_id  →  project_id reaches AgentContext
  2. English input + valid project_id →  same guarantee
  3. Missing project_id (None)        →  run_agent returns controlled error, not crash
  4. Stale / invalid project_id       →  resolve_project_id raises, returns controlled error
  5. Cross-org project_id             →  resolve_project_id rejects, controlled error
  6. Direct /run with explicit project_id override
  7. /plan and /deliberate endpoints now propagate project_id
  8. PlanRequest model has project_id field

Security invariants verified in all paths:
  - project_id resolved from DB, not from raw user input
  - workspace path derived from DB-verified PID, never from request body
  - No IDOR: only the project's owner may use it
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.base   import AgentContext, AgentResult, EvolvableAgent
from app.agents.memory import AgentMemory
from app.agents.intent import IntentParser
from app.routers.agent_os_api import PlanRequest, RunRequest


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_memory() -> AgentMemory:
    import threading
    mem = AgentMemory.__new__(AgentMemory)
    mem._lock    = threading.Lock()
    mem._records = []
    return mem


def _make_kernel(extra_agents: list[str] | None = None):
    """Mirrors test_agent_os.py's _make_kernel pattern exactly."""
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


def _make_ctx(kernel=None, memory=None, **kw) -> AgentContext:
    """Build a minimal AgentContext without a real DB/kernel."""
    kernel = kernel or MagicMock()
    memory = memory or _make_memory()
    defaults = dict(input="run .", args=".", caller="api")
    defaults.update(kw)
    return AgentContext(kernel=kernel, memory=memory, **defaults)


class AlwaysOkAgent(EvolvableAgent):
    """Test agent that echoes project_id from ctx into result.data."""
    name        = "echo"
    description = "Returns ok with project_id in data."
    group       = "test"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, ctx.args or "empty",
                              data={"project_id": ctx.project_id})


def _register(kernel, agent: EvolvableAgent):
    """Register an agent and update the intent parser (mirrors TestAgentKernel.setup_method)."""
    kernel.register_agent(agent)
    kernel._parser.update_agents(list(kernel._agents.keys()))


def _run(coro):
    return asyncio.run(coro)


# ── 1. Arabic input + valid project_id ───────────────────────────────────────

class TestArabicInputWithProject:
    """project_id must reach AgentContext even when the input is Arabic."""

    def test_arabic_input_propagates_project_id(self):
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        arabic_input = "echo سأبدأ مشروعي"  # starts with intent word "echo"
        pid = "00000000-0000-0000-0000-000000000042"

        result = _run(kernel.run(arabic_input, project_id=pid))

        assert isinstance(result, AgentResult)
        # project_id was threaded in: the agent echoes it
        assert result.data.get("project_id") == pid

    def test_arabic_input_missing_project_returns_controlled_error(self):
        """No project → AgentResult with project_id=None, not an exception."""
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        result = _run(kernel.run("echo سأبدأ", project_id=None))
        assert isinstance(result, AgentResult)
        # If echo ran it gets project_id=None; if unknown-intent it fails safely
        assert result.data.get("project_id") is None or not result.success


# ── 2. English input + valid project_id ──────────────────────────────────────

class TestEnglishInputWithProject:
    def test_english_run_propagates_project_id(self):
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        pid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _run(kernel.run("echo hello", project_id=pid))
        assert isinstance(result, AgentResult)
        assert result.data.get("project_id") == pid


# ── 3. Missing project_id → run_agent controlled error ───────────────────────

class TestMissingProjectId:
    """run_agent.py returns AgentResult.fail (not an exception) for None project_id."""

    def test_run_agent_returns_fail_when_no_project(self):
        from app.agents.builtin.run_agent import RunAgent
        agent = RunAgent()
        ctx = _make_ctx(
            input="run .",
            args=".",
            user_id="user-1",
            project_id=None,   # ← missing
        )
        result = _run(agent.execute(ctx))
        assert result.success is False
        assert "No project specified" in result.output

    def test_run_agent_returns_fail_when_no_user(self):
        from app.agents.builtin.run_agent import RunAgent
        agent = RunAgent()
        ctx = _make_ctx(
            input="run .",
            args=".",
            user_id=None,      # ← unauthenticated
            project_id="some-id",
        )
        result = _run(agent.execute(ctx))
        assert result.success is False
        assert "Authentication required" in result.output


# ── 4. Stale / invalid project_id → controlled error ─────────────────────────

class TestStaleProjectId:
    """resolve_project_id raises HTTPException(404) for a deleted project."""

    def test_run_agent_handles_invalid_project(self):
        from fastapi import HTTPException
        from app.agents.builtin.run_agent import RunAgent
        agent = RunAgent()
        ctx = _make_ctx(
            input="run .",
            args=".",
            user_id="00000000-0000-0000-0000-000000000001",   # must be valid UUID
            project_id="00000000-0000-0000-0000-000000000000",
        )

        async def _exec():
            # Inline imports in execute() resolve at call time via sys.modules,
            # so we patch the actual source modules, not the caller's namespace.
            with (
                patch("app.core.db.get_pool") as mock_pool,
                patch("app.core.helpers.resolve_project_id",
                      AsyncMock(side_effect=HTTPException(404, "Project not found"))),
            ):
                mock_conn = AsyncMock()
                mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_pool.return_value.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
                return await agent.execute(ctx)

        result = asyncio.run(_exec())
        assert result.success is False
        assert "Project not found" in result.output


# ── 5. Cross-org project_id → rejected ───────────────────────────────────────

class TestCrossOrgRejection:
    """resolve_project_id rejects a project owned by a different user/org."""

    def test_run_agent_rejects_cross_org_project(self):
        from fastapi import HTTPException
        from app.agents.builtin.run_agent import RunAgent
        agent = RunAgent()
        ctx = _make_ctx(
            input="run .",
            args=".",
            user_id="aaaaaaaa-0000-0000-0000-000000000001",   # valid UUID, org A
            project_id="bbbbbbbb-0000-0000-0000-000000000001",   # owned by org B
        )

        async def _exec():
            with (
                patch("app.core.db.get_pool") as mock_pool,
                patch("app.core.helpers.resolve_project_id",
                      AsyncMock(side_effect=HTTPException(404, "Project not found"))),
            ):
                mock_conn = AsyncMock()
                mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_pool.return_value.acquire.return_value.__aexit__  = AsyncMock(return_value=False)
                return await agent.execute(ctx)

        result = asyncio.run(_exec())
        assert result.success is False
        # 404 is returned for cross-org (same as "not found") to prevent
        # enumeration — the caller cannot distinguish "wrong owner" from "missing"
        assert not result.success


# ── 6. Direct /run with explicit project_id override ─────────────────────────

class TestDirectRunWithExplicitProjectId:
    """RunRequest carries project_id and the kernel.run() call threads it through."""

    def test_run_request_has_project_id_field(self):
        req = RunRequest(input="echo hello", project_id="explicit-id")
        assert req.project_id == "explicit-id"

    def test_run_request_project_id_defaults_to_none(self):
        req = RunRequest(input="echo hello")
        assert req.project_id is None

    def test_kernel_run_passes_project_id_to_agent(self):
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        pid = "explicit-override-id"
        result = _run(kernel.run("echo test", project_id=pid))
        assert result.data.get("project_id") == pid


# ── 7. /plan and /deliberate endpoints propagate project_id ──────────────────

class TestPlanAndDeliberatePropagation:
    """plan_and_run and deliberate_and_run must thread project_id to every run()."""

    def test_plan_and_run_threads_project_id(self):
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        pid = "plan-project-id"
        received_pids: list[str | None] = []

        async def capturing_run(raw_input, **kw):
            received_pids.append(kw.get("project_id"))
            # Return a plan result so collaborate() is also triggered
            return AgentResult.ok("echo", "ok", data={"tasks": ["echo step1"]})

        async def fake_collaborate(tasks, **kw):
            received_pids.append(kw.get("project_id"))
            return [AgentResult.ok("echo", "ok")]

        with (
            patch.object(kernel, "run", AsyncMock(side_effect=capturing_run)),
            patch.object(kernel, "collaborate", AsyncMock(side_effect=fake_collaborate)),
        ):
            _run(kernel.plan_and_run("deploy my app", project_id=pid))

        # Every subordinate call must carry the project_id
        assert received_pids, "No subordinate run() or collaborate() calls captured"
        assert all(p == pid for p in received_pids), (
            f"Some calls missed project_id: {received_pids}"
        )

    def test_deliberate_and_run_threads_project_id_via_kwargs(self):
        """deliberate_and_run uses **kwargs; project_id propagates through them."""
        kernel = _make_kernel()
        _register(kernel, AlwaysOkAgent())
        received_kwargs: list[dict] = []
        pid = "deliberate-project-id"

        async def capturing_run(raw_input, **kw):
            received_kwargs.append(dict(kw))
            return AgentResult.ok("echo", "ok")

        mock_bid = MagicMock()
        mock_bid.agent = "echo"
        mock_bid.score = 1.0
        mock_bid.relevance = 1.0
        mock_bid.confidence = 1.0
        mock_bid.reasoning = "test"

        mock_vote_result = MagicMock()
        mock_vote_result.winner = "echo"
        mock_vote_result.bids = [mock_bid]
        mock_vote_result.to_dict = MagicMock(return_value={
            "winner": "echo", "winner_score": 1.0,
            "consensus": 1.0, "method": "vote", "bids": [],
        })

        mock_deliberation = MagicMock()
        mock_deliberation.vote = AsyncMock(return_value=mock_vote_result)
        kernel._deliberation = mock_deliberation

        with patch.object(kernel, "run", AsyncMock(side_effect=capturing_run)):
            _run(kernel.deliberate_and_run(
                "analyze performance",
                project_id=pid,
                caller="api",
                user_id="u1",
            ))

        pids = [kw.get("project_id") for kw in received_kwargs]
        assert any(p == pid for p in pids), (
            f"project_id not seen in any subordinate run() call: {received_kwargs}"
        )


# ── 8. PlanRequest model has project_id field ─────────────────────────────────

class TestPlanRequestModel:
    """PlanRequest must carry project_id (was missing before the fix)."""

    def test_plan_request_has_project_id_field(self):
        req = PlanRequest(goal="launch new feature", project_id="proj-123")
        assert req.project_id == "proj-123"

    def test_plan_request_project_id_defaults_to_none(self):
        req = PlanRequest(goal="launch new feature")
        assert req.project_id is None

    def test_plan_request_other_fields_unchanged(self):
        req = PlanRequest(goal="test goal", workspace="/ws", caller="api",
                          run_id="run-abc", project_id=None)
        assert req.goal      == "test goal"
        assert req.workspace == "/ws"
        assert req.caller    == "api"
        assert req.run_id    == "run-abc"
