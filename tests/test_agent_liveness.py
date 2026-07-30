"""
AgentOS agent liveness tests — the event-bus-to-WS bridge
(app/agents/liveness.py) that turns AgentKernel.run()'s existing
"agent.started"/"agent.finished" events into live /ws/system frames,
plus the /ws/system auth gate and the GET /api/agentos/agents snapshot
merge.

No live Postgres/Redis — everything here is pure in-process state and
mocked collaborators (same pattern as tests/test_presence.py).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_liveness_state():
    """app/agents/liveness.py's `_running`/`_run_owners` dicts are
    module-level, in-process state — reset them around every test so runs
    don't leak into each other."""
    import app.agents.liveness as liveness
    liveness._running.clear()
    liveness._run_owners.clear()
    yield
    liveness._running.clear()
    liveness._run_owners.clear()


class _FakeEvent:
    def __init__(self, type_: str, data: dict):
        self.type = type_
        self.data = data


# ── Event bridge ─────────────────────────────────────────────────────────────

class TestAgentLivenessBridge:
    def test_agent_started_marks_running_and_broadcasts(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("agent.started", {"agent": "analyze", "run_id": "r1"})))

        assert liveness.is_running("analyze") is True
        fake_ws.broadcast.assert_awaited_once_with(
            "system", {"agent": "analyze", "status": "running", "run_id": "r1"},
        )

    def test_agent_finished_clears_running_and_broadcasts_result(self):
        import app.agents.liveness as liveness
        liveness._running["analyze"] = {"r1": 0.0}
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent(
                "agent.finished", {"agent": "analyze", "run_id": "r1", "success": True, "duration_ms": 42},
            )))

        assert liveness.is_running("analyze") is False
        frame = fake_ws.broadcast.call_args.args[1]
        assert frame == {
            "agent": "analyze", "status": "idle", "run_id": "r1",
            "success": True, "duration_ms": 42,
        }

    def test_second_concurrent_run_finishing_leaves_agent_marked_running(self):
        """Two concurrent runs of the same agent — the first to finish must
        not flip the agent to idle while the second is still in flight."""
        import app.agents.liveness as liveness
        liveness._running["analyze"] = {"r1": 0.0, "r2": 1.0}
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent(
                "agent.finished", {"agent": "analyze", "run_id": "r1", "success": True, "duration_ms": 10},
            )))

        assert liveness.is_running("analyze") is True
        frame = fake_ws.broadcast.call_args.args[1]
        assert frame["status"] == "running"

    def test_finished_for_never_started_agent_is_a_noop_not_a_crash(self):
        """A finished event without a matching started (e.g. this process
        restarted mid-run) must not raise — pop(run_id, None) handles it."""
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent(
                "agent.finished", {"agent": "ghost", "run_id": "r-missing", "success": False, "duration_ms": 0},
            )))

        assert liveness.is_running("ghost") is False

    def test_event_without_agent_name_is_ignored(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("agent.started", {"run_id": "r1"})))

        fake_ws.broadcast.assert_not_awaited()

    def test_event_without_run_id_is_ignored(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("agent.started", {"agent": "analyze"})))

        fake_ws.broadcast.assert_not_awaited()
        assert liveness.is_running("analyze") is False

    def test_unrelated_event_type_is_ignored(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("workflow.completed", {"agent": "analyze"})))

        fake_ws.broadcast.assert_not_awaited()
        import app.agents.liveness as liveness2
        assert liveness2.is_running("analyze") is False

    def test_broadcast_failure_is_swallowed(self):
        """Mirrors the notification dispatcher's own contract: a broken
        broadcast must never propagate back into AgentKernel.run()'s
        request path."""
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock(side_effect=RuntimeError("ws down"))

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("agent.started", {"agent": "analyze"})))  # must not raise

    def test_wire_agent_liveness_is_idempotent(self):
        import app.agents.liveness as liveness
        liveness._wired = False
        try:
            fake_bus = MagicMock()
            fake_bus.subscribe = MagicMock()
            with patch("app.core.events.get_event_bus", return_value=fake_bus):
                liveness.wire_agent_liveness()
                liveness.wire_agent_liveness()
            # 2 subscribe calls (one per event type) from the first wiring
            # only — the second call must be a no-op, not 4 total.
            assert fake_bus.subscribe.call_count == 2
        finally:
            liveness._wired = False

    def test_wire_agent_liveness_subscribes_both_event_types(self):
        import app.agents.liveness as liveness
        liveness._wired = False
        try:
            fake_bus = MagicMock()
            with patch("app.core.events.get_event_bus", return_value=fake_bus):
                liveness.wire_agent_liveness()
            subscribed_types = {c.args[0] for c in fake_bus.subscribe.call_args_list}
            assert subscribed_types == {"agent.started", "agent.finished"}
        finally:
            liveness._wired = False


# ── Snapshot ─────────────────────────────────────────────────────────────────

class TestAgentLivenessSnapshot:
    def test_snapshot_reports_only_running_agents(self):
        import app.agents.liveness as liveness
        liveness._running["busy_agent"] = {"r1": 0.0}
        snap = liveness.snapshot()
        assert "busy_agent" in snap
        assert snap["busy_agent"]["status"] == "running"
        assert "idle_agent" not in snap

    def test_empty_snapshot_when_nothing_running(self):
        import app.agents.liveness as liveness
        assert liveness.snapshot() == {}


# ── agent.started/agent.finished are declared, real EVENT_TYPES ────────────────

class TestPublishStepBroadcastsOnPerRunTopic:
    """publish_step() carries a run's actual content (input text, search
    queries, URLs) — it must land on a per-run topic (system:{run_id}),
    not the shared "system" topic every /ws/system connection receives,
    so isolation happens at the subscription boundary rather than relying
    on every client to filter out runs that aren't theirs."""

    def test_step_broadcasts_on_system_colon_run_id_not_shared_system_topic(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("run-42", "browser", "Opening https://example.com", "terminal"))

        topic, frame = fake_ws.broadcast.call_args.args
        assert topic == "system:run-42"
        assert topic != "system"
        assert frame == {
            "run_id": "run-42", "agent": "browser",
            "step": "Opening https://example.com", "kind": "terminal",
        }

    def test_liveness_dot_still_broadcasts_on_the_shared_system_topic(self):
        """The started/finished liveness dot (_on_agent_event, unlike
        publish_step) is intentionally unchanged by the per-run isolation
        fix — agent name + running/idle status isn't run-content-sensitive,
        so it keeps going on the one shared "system" topic."""
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness._on_agent_event(_FakeEvent("agent.started", {"agent": "analyze", "run_id": "r1"})))

        assert fake_ws.broadcast.call_args.args[0] == "system"

    def test_missing_run_id_is_a_noop_not_a_crash(self):
        import app.agents.liveness as liveness
        fake_ws = MagicMock()
        fake_ws.broadcast = AsyncMock()

        with patch("app.routers.ws.manager", fake_ws):
            run(liveness.publish_step("", "browser", "step"))  # must not raise

        fake_ws.broadcast.assert_not_awaited()


class TestRunOwnerRegistry:
    """register_run_owner()/get_run_owner() — the run_id -> verified-caller
    record /ws/system/{run_id} checks so an unguessable run_id alone isn't
    treated as sufficient authorization to watch someone else's run."""

    def test_unregistered_run_id_has_no_owner_on_record(self):
        import app.agents.liveness as liveness
        assert liveness.get_run_owner("never-registered") is None

    def test_registered_owner_is_returned(self):
        import app.agents.liveness as liveness
        liveness.register_run_owner("r1", "user-a")
        assert liveness.get_run_owner("r1") == "user-a"

    def test_anonymous_caller_registers_explicitly_as_none(self):
        import app.agents.liveness as liveness
        liveness.register_run_owner("r1", None)
        assert liveness.get_run_owner("r1") is None

    def test_empty_run_id_is_not_registered(self):
        import app.agents.liveness as liveness
        liveness.register_run_owner("", "user-a")
        assert liveness._run_owners == {}


class TestAgentEventsAreDeclared:
    def test_agent_lifecycle_events_are_in_event_types(self):
        """AgentKernel.run() publishes these unconditionally on every
        invocation (app/agents/kernel.py) — if they weren't declared,
        EventBus.publish() would silently drop them and this whole bridge
        would never fire (see the billing.payment_failed regression this
        codebase already hit once for exactly this class of bug)."""
        from app.core.events.bus import EVENT_TYPES
        assert "agent.started" in EVENT_TYPES
        assert "agent.finished" in EVENT_TYPES


# ── /ws/system auth gate ────────────────────────────────────────────────────

@pytest.fixture()
def ws_client():
    from fastapi import FastAPI
    from app.routers.ws import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token_for(user_id: str):
    from app.core.jwt_utils import make_access_token
    return make_access_token(user_id, "user@example.com")


def _token():
    return _token_for(str(uuid.uuid4()))


class TestSystemWsAuth:
    def test_unauthenticated_connection_is_rejected(self, ws_client):
        with pytest.raises(Exception):  # noqa: B017 - starlette raises on the 4401 close
            with ws_client.websocket_connect("/ws/system") as ws:
                ws.receive_json()

    def test_authenticated_connection_succeeds(self, ws_client):
        with ws_client.websocket_connect(f"/ws/system?token={_token()}") as ws:
            connected = ws.receive_json()
            assert connected == {"type": "connected", "topic": "system"}


# ── /ws/system/{run_id} per-run channel isolation ───────────────────────────

class TestSystemRunWsAuth:
    def test_unauthenticated_connection_is_rejected(self, ws_client):
        with pytest.raises(Exception):  # noqa: B017 - starlette raises on the 4401 close
            with ws_client.websocket_connect("/ws/system/run-42") as ws:
                ws.receive_json()

    def test_authenticated_connection_subscribes_to_the_per_run_topic(self, ws_client):
        with ws_client.websocket_connect(f"/ws/system/run-42?token={_token()}") as ws:
            connected = ws.receive_json()
            assert connected == {"type": "connected", "topic": "system:run-42"}

    def test_two_different_runs_get_two_different_topics(self, ws_client):
        with ws_client.websocket_connect(f"/ws/system/run-a?token={_token()}") as ws_a, \
             ws_client.websocket_connect(f"/ws/system/run-b?token={_token()}") as ws_b:
            assert ws_a.receive_json()["topic"] == "system:run-a"
            assert ws_b.receive_json()["topic"] == "system:run-b"


class TestSystemRunWsOwnershipCheck:
    """An unguessable run_id must not be sufficient on its own — the
    endpoint has to check the connecting user against the run's recorded
    owner (see AgentKernel.run() -> liveness.register_run_owner)."""

    def test_owner_can_connect_to_their_own_run(self, ws_client):
        import app.agents.liveness as liveness
        owner_id = str(uuid.uuid4())
        liveness.register_run_owner("run-owned", owner_id)

        with ws_client.websocket_connect(
            f"/ws/system/run-owned?token={_token_for(owner_id)}",
        ) as ws:
            connected = ws.receive_json()
            assert connected == {"type": "connected", "topic": "system:run-owned"}

    def test_a_different_user_is_rejected(self, ws_client):
        import app.agents.liveness as liveness
        liveness.register_run_owner("run-owned", str(uuid.uuid4()))

        with pytest.raises(Exception):  # noqa: B017 - starlette raises on the 4403 close
            with ws_client.websocket_connect(f"/ws/system/run-owned?token={_token()}") as ws:
                ws.receive_json()

    def test_run_with_no_owner_on_record_allows_any_authenticated_user(self, ws_client):
        # Covers both "run hasn't started yet" and "started by an
        # unauthenticated caller" — same fallback deliverables use.
        with ws_client.websocket_connect(f"/ws/system/run-unrecorded?token={_token()}") as ws:
            connected = ws.receive_json()
            assert connected == {"type": "connected", "topic": "system:run-unrecorded"}


class TestConnectionManagerPerRunTopicIsolation:
    """Exercises the real _ConnectionManager (not liveness.py's mocked
    boundary) to confirm broadcast() fan-out is actually scoped per topic
    — a subscriber to system:{run_id} for one run must never receive a
    frame broadcast on a different run's topic."""

    def test_broadcast_on_one_run_topic_does_not_reach_another_runs_subscriber(self):
        from app.routers.ws import _ConnectionManager
        from starlette.websockets import WebSocketState

        manager = _ConnectionManager()

        ws_run_a = MagicMock()
        ws_run_a.application_state = WebSocketState.CONNECTED
        ws_run_a.send_text = AsyncMock()

        ws_run_b = MagicMock()
        ws_run_b.application_state = WebSocketState.CONNECTED
        ws_run_b.send_text = AsyncMock()

        run(manager.connect(ws_run_a, "system:run-a"))
        run(manager.connect(ws_run_b, "system:run-b"))

        run(manager.broadcast("system:run-a", {"run_id": "run-a", "step": "secret input for run a"}))

        ws_run_a.send_text.assert_awaited_once()
        ws_run_b.send_text.assert_not_awaited()


# ── GET /api/agentos/agents liveness merge ──────────────────────────────────

class TestAgentsEndpointLivenessMerge:
    def test_running_agent_reports_live_status_in_response(self):
        from app.routers.agent_os_api import agentos_agents

        fake_agent = MagicMock()
        fake_agent.name = "analyze"
        fake_agent.to_dict.return_value = {"name": "analyze", "description": "d", "group": "core"}

        fake_kernel = MagicMock()
        fake_kernel.visible_agents.return_value = [fake_agent]

        fake_stats = MagicMock()
        fake_stats.to_dict.return_value = {"call_count": 1, "avg_ms": 10.0, "success_rate": 1.0}
        fake_memory = MagicMock()
        fake_memory.stats.return_value = fake_stats

        fake_request = MagicMock()

        with patch("app.agents.kernel.get_agent_kernel", return_value=fake_kernel), \
             patch("app.agents.memory.get_memory", return_value=fake_memory), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.agents.liveness.snapshot", return_value={"analyze": {"status": "running", "duration_s": 2.0}}):
            result = run(agentos_agents(fake_request))

        assert result["agents"][0]["live"] == {"status": "running", "duration_s": 2.0}

    def test_idle_agent_defaults_to_idle_status(self):
        from app.routers.agent_os_api import agentos_agents

        fake_agent = MagicMock()
        fake_agent.name = "deploy"
        fake_agent.to_dict.return_value = {"name": "deploy", "description": "d", "group": "core"}

        fake_kernel = MagicMock()
        fake_kernel.visible_agents.return_value = [fake_agent]

        fake_stats = MagicMock()
        fake_stats.to_dict.return_value = {"call_count": 0, "avg_ms": 0.0, "success_rate": 0.0}
        fake_memory = MagicMock()
        fake_memory.stats.return_value = fake_stats

        fake_request = MagicMock()

        with patch("app.agents.kernel.get_agent_kernel", return_value=fake_kernel), \
             patch("app.agents.memory.get_memory", return_value=fake_memory), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.agents.liveness.snapshot", return_value={}):
            result = run(agentos_agents(fake_request))

        assert result["agents"][0]["live"] == {"status": "idle"}
