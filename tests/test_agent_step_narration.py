"""
AgentOS live step narration tests — AgentContext.step()/publish_step(),
AgentKernel.run()'s run_id generation/threading, and the run_agent.py
fix for a pre-existing crash (TypedEvent has no .get(), and "error" was
never a real event_type — see app/execution/platform/events.py).

No live Postgres/Redis — pure in-process logic + mocked collaborators
(same pattern as the other AgentOS test files).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


# ── publish_step ─────────────────────────────────────────────────────────────

class TestPublishStep:
    def test_broadcasts_a_well_formed_frame(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("r1", "build", "Running npm build", "terminal", command=["npm", "build"]))

        # Broadcasts on a topic scoped to this run (not the shared "system"
        # topic every /ws/system connection receives) — see
        # tests/test_agent_liveness.py's TestPublishStepBroadcastsOnPerRunTopic
        # for the isolation-focused coverage of this.
        fake_ws.broadcast.assert_awaited_once_with("system:r1", {
            "run_id": "r1", "agent": "build", "step": "Running npm build",
            "kind": "terminal", "command": ["npm", "build"],
        })

    def test_missing_run_id_is_a_noop(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("", "build", "step"))

        fake_ws.broadcast.assert_not_awaited()

    def test_missing_agent_name_is_a_noop(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("r1", "", "step"))

        fake_ws.broadcast.assert_not_awaited()

    def test_broadcast_failure_is_swallowed(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock(side_effect=RuntimeError("ws down"))

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("r1", "build", "step"))  # must not raise


# ── AgentContext.step() ──────────────────────────────────────────────────────

class TestAgentContextStep:
    def test_step_forwards_run_id_and_agent_name_hint(self):
        from app.agents.base import AgentContext

        ctx = AgentContext(input="x", args="", kernel=None, memory=None, run_id="r1")
        ctx._agent_name_hint = "build"

        fake_publish = AsyncMock()
        with patch("app.agents.liveness.publish_step", fake_publish):
            run(ctx.step("Doing a thing", "info", extra=1))

        fake_publish.assert_awaited_once_with("r1", "build", "Doing a thing", "info", extra=1)

    def test_step_never_raises_even_if_broadcast_layer_is_broken(self):
        from app.agents.base import AgentContext

        ctx = AgentContext(input="x", args="", kernel=None, memory=None, run_id="r1")
        ctx._agent_name_hint = "build"

        with patch("app.agents.liveness.publish_step", AsyncMock(side_effect=RuntimeError("boom"))):
            run(ctx.step("Doing a thing"))  # must not raise

    def test_evolvable_agent_run_sets_the_name_hint_before_execute(self):
        """EvolvableAgent.run() (the timed wrapper AgentKernel calls) must
        stamp ctx._agent_name_hint = self.name before execute() runs, so
        ctx.step() calls from inside execute() know which agent they're for
        without every agent threading its own name through by hand."""
        from app.agents.base import AgentContext, AgentResult, EvolvableAgent

        seen_hint = {}

        class ProbeAgent(EvolvableAgent):
            name = "probe"
            description = "test"

            async def execute(self, ctx: AgentContext) -> AgentResult:
                seen_hint["value"] = ctx._agent_name_hint
                return AgentResult.ok(self.name, "ok")

        ctx = AgentContext(input="x", args="", kernel=None, memory=None, run_id="r1")
        run(ProbeAgent().run(ctx))

        assert seen_hint["value"] == "probe"


# ── AgentKernel.run() run_id threading ───────────────────────────────────────

def _make_isolated_kernel():
    """Mirrors tests/test_agent_os.py's _make_kernel() — bypasses __init__
    so this test doesn't touch the process-wide AgentMemory singleton."""
    import threading
    from app.agents.kernel import AgentKernel
    from app.agents.intent import IntentParser
    from app.agents.memory import AgentMemory
    from app.plugins.registry_guard import OwnershipTracker

    mem = AgentMemory.__new__(AgentMemory)
    mem._lock = threading.Lock()
    mem._records = []

    k = AgentKernel.__new__(AgentKernel)
    k._agents = {}
    k._agent_owners = OwnershipTracker("agent")
    k._memory = mem
    k._parser = IntentParser()
    k._booted = True
    k._modifier = k._reloader = k._evolution = None
    k._router = k._reflector = k._deliberation = k._autonomy = k._loop = None
    return k


def _probe_agent_class(seen: dict):
    """Built fresh per test so each test's closure captures its own `seen` dict."""
    from app.agents.base import AgentContext, AgentResult, EvolvableAgent

    class _Probe(EvolvableAgent):
        name = "probe"
        description = "test"

        async def execute(self, ctx: AgentContext) -> AgentResult:
            seen["run_id"] = ctx.run_id
            return AgentResult.ok(self.name, "ok")

    return _Probe


class TestKernelRunIdThreading:
    def test_generates_a_run_id_when_none_supplied(self):
        seen: dict = {}
        kernel = _make_isolated_kernel()
        kernel.register_agent(_probe_agent_class(seen)())

        run(kernel.run("probe", organization_id=None))

        assert seen["run_id"]
        assert isinstance(seen["run_id"], str)

    def test_uses_the_caller_supplied_run_id_verbatim(self):
        seen: dict = {}
        kernel = _make_isolated_kernel()
        kernel.register_agent(_probe_agent_class(seen)())

        run(kernel.run("probe", organization_id=None, run_id="client-chosen-id"))

        assert seen["run_id"] == "client-chosen-id"

    def test_started_and_finished_events_carry_the_same_run_id(self):
        seen: dict = {}
        kernel = _make_isolated_kernel()
        kernel.register_agent(_probe_agent_class(seen)())

        published = []

        async def fake_publish(event_type, agent_name, **data):
            published.append((event_type, agent_name, data.get("run_id")))

        with patch("app.agents.kernel._publish_agent_event", fake_publish):
            run(kernel.run("probe", organization_id=None, run_id="fixed-id"))

        assert ("agent.started", "probe", "fixed-id") in published
        assert ("agent.finished", "probe", "fixed-id") in published

    def test_records_the_verified_caller_as_the_runs_owner(self):
        """/ws/system/{run_id} (app/routers/ws.py) checks this record
        before letting a connection subscribe — an unguessable run_id
        alone isn't treated as proof of authorization."""
        import app.agents.liveness as liveness
        seen: dict = {}
        kernel = _make_isolated_kernel()
        kernel.register_agent(_probe_agent_class(seen)())

        liveness._run_owners.clear()
        try:
            run(kernel.run("probe", organization_id=None, user_id="caller-1", run_id="fixed-id"))
            assert liveness.get_run_owner("fixed-id") == "caller-1"
        finally:
            liveness._run_owners.clear()

    def test_anonymous_caller_records_no_owner(self):
        import app.agents.liveness as liveness
        seen: dict = {}
        kernel = _make_isolated_kernel()
        kernel.register_agent(_probe_agent_class(seen)())

        liveness._run_owners.clear()
        try:
            run(kernel.run("probe", organization_id=None, run_id="fixed-id"))
            assert liveness.get_run_owner("fixed-id") is None
            assert "fixed-id" in liveness._run_owners  # explicitly recorded, not just absent
        finally:
            liveness._run_owners.clear()


# ── run_agent.py: TypedEvent handling + failure detection ──────────────────────

class _FakeTypedEvent:
    """Stand-in for app.execution.platform.events.TypedEvent — the real
    class has no .get()/.__getitem__, only .to_sse_dict()."""
    def __init__(self, d: dict):
        self._d = d

    def to_sse_dict(self) -> dict:
        return self._d


def _owned_run_context(run_id: str) -> "AgentContext":  # noqa: F821 - imported per-test
    """A ctx that will pass run_agent.py's ownership guard (see its
    security-fix docstring): user_id + project_id set, and a mocked
    get_pool()/resolve_project_id() the guard will call. Callers must
    still patch app.core.db.get_pool to the returned pool and
    app.core.filesystem.WORKSPACES to a temp dir before invoking
    RunAgent().execute()."""
    from app.agents.base import AgentContext

    project_id = str(uuid.uuid4())
    ctx = AgentContext(
        input="x", args="", kernel=None, memory=None, run_id=run_id,
        user_id=str(uuid.uuid4()), project_id=project_id,
    )
    ctx._agent_name_hint = "run"

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)  # resolve_project_id: owned
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, pool


class TestRunAgentEventHandling:
    def test_converts_typed_events_via_to_sse_dict_not_get(self):
        """Regression: engine.run() yields TypedEvent dataclass instances,
        which have no .get() — calling .get() directly on them raises
        AttributeError. run_agent.py must call .to_sse_dict() first."""
        from app.agents.builtin.run_agent import RunAgent

        async def fake_engine_run(ws, project_id, execution_id):
            yield _FakeTypedEvent({"type": "execution_started", "project_id": project_id})
            yield _FakeTypedEvent({"type": "execution_finished", "success": True})

        fake_engine = MagicMock()
        fake_engine.run = fake_engine_run

        ctx, pool = _owned_run_context("r1")

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, \
             patch("app.execution.platform.engine.UnifiedExecutionEngine", return_value=fake_engine), \
             patch("app.agents.liveness.publish_step", AsyncMock()), \
             patch("app.core.db.get_pool", return_value=pool), \
             patch("app.core.filesystem.WORKSPACES", Path(tmp)):
            # Pre-flight guard: workspace must contain project files so
            # _detect_runtime_type() passes and the engine is reached.
            ws = Path(tmp) / ctx.project_id
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "package.json").write_text('{"name":"test"}')
            result = run(RunAgent().execute(ctx))

        assert result.success is True

    def test_a_failed_event_type_is_detected_and_reported(self):
        """Regression: the old check compared against the literal string
        "error", which is not a real event_type (see _FAILURE_EVENT_TYPES
        in run_agent.py) — a real failure event was never caught."""
        from app.agents.builtin.run_agent import RunAgent

        async def fake_engine_run(ws, project_id, execution_id):
            yield _FakeTypedEvent({"type": "execution_started"})
            yield _FakeTypedEvent({"type": "build_failed", "message": "npm build exited 1"})

        fake_engine = MagicMock()
        fake_engine.run = fake_engine_run

        ctx, pool = _owned_run_context("r1")

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, \
             patch("app.execution.platform.engine.UnifiedExecutionEngine", return_value=fake_engine), \
             patch("app.agents.liveness.publish_step", AsyncMock()), \
             patch("app.core.db.get_pool", return_value=pool), \
             patch("app.core.filesystem.WORKSPACES", Path(tmp)):
            ws = Path(tmp) / ctx.project_id
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "package.json").write_text('{"name":"test"}')
            result = run(RunAgent().execute(ctx))

        assert result.success is False
        assert result.error == "npm build exited 1"

    def test_narrates_each_event_live_via_ctx_step(self):
        from app.agents.builtin.run_agent import RunAgent

        async def fake_engine_run(ws, project_id, execution_id):
            yield _FakeTypedEvent({"type": "install_progress", "line": "installing deps..."})

        fake_engine = MagicMock()
        fake_engine.run = fake_engine_run

        ctx, pool = _owned_run_context("r1")

        fake_publish = AsyncMock()
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, \
             patch("app.execution.platform.engine.UnifiedExecutionEngine", return_value=fake_engine), \
             patch("app.agents.liveness.publish_step", fake_publish), \
             patch("app.core.db.get_pool", return_value=pool), \
             patch("app.core.filesystem.WORKSPACES", Path(tmp)):
            ws = Path(tmp) / ctx.project_id
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "package.json").write_text('{"name":"test"}')
            run(RunAgent().execute(ctx))

        narrated = [c.args[2] for c in fake_publish.call_args_list]
        assert "installing deps..." in narrated
