"""
Regression tests for the CRITICAL /ws/agent/{session_id} fix (see
app/routers/ws.py::agent_ws's docstring):

1. The endpoint previously accepted any connection with no auth check at
   all — the only one of this file's 5 WS endpoints missing it.
2. Its "subscribe" message forwarded any client-supplied topic string
   verbatim to the connection manager with zero validation, letting an
   unauthenticated connection eavesdrop on any other topic in the app
   (another user's chat room, notifications, presence, or a live AgentOS
   run's step narration).

Same fixture/token-helper pattern as tests/test_agent_liveness.py's
TestSystemWsAuth (the analogous, already-established WS auth test suite).
"""
from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def ws_client():
    from fastapi import FastAPI
    from app.routers.ws import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _token_for(user_id: str) -> str:
    from app.core.jwt_utils import make_access_token
    return make_access_token(user_id, "user@example.com")


def _token() -> str:
    return _token_for(str(uuid.uuid4()))


class TestAgentWsAuth:
    def test_unauthenticated_connection_is_rejected(self, ws_client):
        with pytest.raises(Exception):  # noqa: B017 - starlette raises on the 4401 close
            with ws_client.websocket_connect("/ws/agent/sess-1") as ws:
                ws.receive_json()

    def test_authenticated_connection_succeeds(self, ws_client):
        with ws_client.websocket_connect(f"/ws/agent/sess-1?token={_token()}") as ws:
            connected = ws.receive_json()
            assert connected == {
                "type": "connected", "session_id": "sess-1", "topic": "agent:sess-1",
            }

    def test_cancel_still_broadcasts_control_topic(self, ws_client):
        """Regression check: the auth fix must not break the pre-existing
        cancel flow — the one legitimate control message this endpoint
        already supported."""
        with ws_client.websocket_connect(f"/ws/agent/sess-1?token={_token()}") as ws:
            ws.receive_json()  # "connected"
            ws.send_json({"type": "cancel"})
            ack = ws.receive_json()
            assert ack == {"type": "ack", "action": "cancel"}


class TestAgentWsSubscribeIsRestricted:
    def test_subscribing_to_an_arbitrary_topic_is_rejected(self, ws_client):
        with ws_client.websocket_connect(f"/ws/agent/sess-1?token={_token()}") as ws:
            ws.receive_json()  # "connected"
            ws.send_json({"type": "subscribe", "topic": "notifications:some-other-user"})
            reply = ws.receive_json()
            assert reply == {"type": "error", "message": "topic not permitted"}

    def test_subscribing_to_a_chat_or_presence_topic_is_rejected(self, ws_client):
        """The exact exploit shape from the audit: eavesdrop on another
        tenant's chat room or a user's presence/notifications feed."""
        with ws_client.websocket_connect(f"/ws/agent/sess-1?token={_token()}") as ws:
            ws.receive_json()
            for evil_topic in ("chat:org:some-org-id", "presence:some-user-id", "system:some-run-id"):
                ws.send_json({"type": "subscribe", "topic": evil_topic})
                reply = ws.receive_json()
                assert reply == {"type": "error", "message": "topic not permitted"}, evil_topic

    def test_subscribing_to_its_own_session_subtopic_is_allowed(self, ws_client):
        with ws_client.websocket_connect(f"/ws/agent/sess-1?token={_token()}") as ws:
            ws.receive_json()  # "connected"
            ws.send_json({"type": "subscribe", "topic": "agent:sess-1:control"})
            reply = ws.receive_json()
            assert reply == {"type": "subscribed", "topic": "agent:sess-1:control"}

    def test_disconnect_cleans_up_every_subscribed_topic_not_just_the_original(self, ws_client):
        """Regression test for the memory leak this same fix closed:
        previously only the original `agent:{session_id}` topic was
        removed from the connection manager on disconnect — any extra
        topic subscribed via "subscribe" stayed registered forever."""
        from app.routers.ws import manager

        with ws_client.websocket_connect(f"/ws/agent/sess-2?token={_token()}") as ws:
            ws.receive_json()
            ws.send_json({"type": "subscribe", "topic": "agent:sess-2:control"})
            ws.receive_json()
            assert manager.subscriber_count("agent:sess-2") == 1
            assert manager.subscriber_count("agent:sess-2:control") == 1

        assert manager.subscriber_count("agent:sess-2") == 0
        assert manager.subscriber_count("agent:sess-2:control") == 0
