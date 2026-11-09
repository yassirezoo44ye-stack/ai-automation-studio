"""Regression tests for agent-stream save acknowledgments and ownership.

All database and inference behavior is faked; the tests never access production
storage or invoke an AI provider.
"""
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.agents import router


class _Bulkhead:
    def __init__(self, fail=False):
        self.fail = fail

    def acquire(self):
        @asynccontextmanager
        async def slot():
            if self.fail:
                raise RuntimeError("at capacity")
            yield
        return slot()


def _test_client(*, fail_assistant_save=False, bulkhead_fail=False, owns_conversation=True, timeline=None):
    uid, agent_id, conv_id, project_id = (uuid.uuid4() for _ in range(4))
    timeline = timeline if timeline is not None else []
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": agent_id, "model": "claude-sonnet-4-6", "system_prompt": "test system",
    })
    conn.fetchval = AsyncMock(return_value=1 if owns_conversation else None)
    conn.fetch = AsyncMock(return_value=[])

    async def execute(query, *args):
        if "INSERT INTO messages" in query and "'user'" in query:
            timeline.append("user_saved")
        if "INSERT INTO messages" in query and "'assistant'" in query:
            timeline.append("assistant_saved")
            if fail_assistant_save:
                raise RuntimeError("simulated database failure")
        return "UPDATE 1"

    conn.execute = AsyncMock(side_effect=execute)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    async def fake_provider_stream(*_args, **_kwargs):
        timeline.append("provider_started")
        yield {"type": "delta", "text": "reply"}

    app = FastAPI()
    app.include_router(router)
    patches = [
        patch("app.routers.agents.get_pool", return_value=pool),
        patch("app.routers.agents.owner_user_id", new=AsyncMock(return_value=uid)),
        patch("app.routers.agents.resolve_project_id", new=AsyncMock(return_value=project_id)),
        patch("app.routers.agents.ensure_agents_table", new=AsyncMock()),
        patch("app.routers.agents.ai_rate_limit"),
        patch("app.routers.agents.check_org_quota", new=AsyncMock(return_value=None)),
        patch("app.core.reliability.get_bulkhead", return_value=_Bulkhead(fail=bulkhead_fail)),
        patch("app.routers.agents.InferenceEngine.stream", new=fake_provider_stream),
    ]
    for item in patches:
        item.start()
    client = TestClient(app, raise_server_exceptions=False)
    client._cleanup_patches = patches
    client._timeline = timeline
    client._agent_id = agent_id
    client._conversation_id = conv_id
    client._conn = conn
    return client


def _close(client):
    client.close()
    for item in client._cleanup_patches:
        item.stop()


def _events(response_text):
    return [json.loads(frame[6:]) for frame in response_text.split("\n\n") if frame.startswith("data: ")]


def test_agent_stream_acknowledges_saved_user_message_before_capacity_rejection():
    client = _test_client(bulkhead_fail=True)
    try:
        response = client.post(
            f"/api/agents/{client._agent_id}/chat/stream",
            json={"agent_id": str(client._agent_id), "project_id": "demo", "prompt": "keep this"},
        )
        events = _events(response.text)
    finally:
        _close(client)

    assert response.status_code == 200
    assert events[0]["type"] == "conv_id"
    assert events[1]["type"] == "error"
    assert "user_saved" in client._timeline
    assert "provider_started" not in client._timeline
    assert all(event["type"] != "done" for event in events)


def test_agent_stream_persists_assistant_reply_before_done():
    client = _test_client()
    try:
        response = client.post(
            f"/api/agents/{client._agent_id}/chat/stream",
            json={"agent_id": str(client._agent_id), "project_id": "demo", "prompt": "test"},
        )
        events = _events(response.text)
    finally:
        _close(client)

    assert response.status_code == 200
    assert client._timeline.index("provider_started") < client._timeline.index("assistant_saved")
    assert [event["type"] for event in events] == ["conv_id", "delta", "done"]


def test_failed_assistant_persistence_never_emits_done():
    client = _test_client(fail_assistant_save=True)
    try:
        response = client.post(
            f"/api/agents/{client._agent_id}/chat/stream",
            json={"agent_id": str(client._agent_id), "project_id": "demo", "prompt": "test"},
        )
        events = _events(response.text)
    finally:
        _close(client)

    assert response.status_code == 200
    assert events[-1]["type"] == "error"
    assert "Failed to save reply" in events[-1]["message"]
    assert all(event["type"] != "done" for event in events)


def test_agent_stream_does_not_read_or_write_foreign_conversation():
    client = _test_client(owns_conversation=False)
    try:
        response = client.post(
            f"/api/agents/{client._agent_id}/chat/stream",
            json={
                "agent_id": str(client._agent_id), "project_id": "demo", "prompt": "private",
                "conversation_id": str(client._conversation_id),
            },
        )
    finally:
        _close(client)

    assert response.status_code == 404
    client._conn.fetch.assert_not_called()
    client._conn.execute.assert_not_called()
    assert "provider_started" not in client._timeline
