"""A streaming completion must follow a real PostgreSQL commit, even on disconnect."""
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
import pytest_asyncio

from app.routers import agents


@pytest_asyncio.fixture
async def agent_database(monkeypatch):
    dsn = os.getenv("FLOW_TEST_DATABASE_URL") or os.getenv("STUDY_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated test PostgreSQL required")
    schema = "agent_stream_" + uuid.uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f"CREATE SCHEMA {schema}")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, server_settings={"search_path": schema})
    owner, agent_id, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE projects(id UUID PRIMARY KEY, user_id UUID);
                CREATE TABLE conversations(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), project_id UUID, title TEXT, updated_at TIMESTAMPTZ);
                CREATE TABLE messages(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id UUID, role TEXT, content TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
                CREATE TABLE ai_agents(id UUID PRIMARY KEY, user_id UUID, system_prompt TEXT, model TEXT, message_count INT DEFAULT 0, updated_at TIMESTAMPTZ, skill_ids TEXT[]);
            """)
            await conn.execute("INSERT INTO projects VALUES($1,$2)", project, owner)
            await conn.execute("INSERT INTO ai_agents(id,user_id,system_prompt,model) VALUES($1,$2,'Be helpful','claude-sonnet-4-6')", agent_id, owner)
        monkeypatch.setattr(agents, "get_pool", lambda: pool)
        monkeypatch.setattr(agents, "ensure_agents_table", AsyncMock())
        monkeypatch.setattr(agents, "owner_user_id", AsyncMock(return_value=owner))
        monkeypatch.setattr(agents, "check_org_quota", AsyncMock(return_value=None))
        monkeypatch.setattr(agents, "ai_rate_limit", lambda _: None)

        async def provider(*args, **kwargs):
            yield {"type": "delta", "text": "persisted reply"}
        monkeypatch.setattr(agents.InferenceEngine, "stream", provider)
        yield pool, agent_id, project
    finally:
        await pool.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


async def response_for(agent_id, project):
    return await agents.agent_chat_stream(str(agent_id), agents.AgentChatRequest(agent_id=str(agent_id), prompt="hello", project_id=str(project)), MagicMock())


@pytest.mark.asyncio
async def test_done_means_committed_even_when_client_immediately_disconnects(agent_database):
    pool, agent_id, project = agent_database
    response = await response_for(agent_id, project)
    events = []
    async for frame in response.body_iterator:
        event = json.loads(frame.removeprefix("data: "))
        events.append(event)
        if event["type"] == "done":
            await response.body_iterator.aclose()
            break
    assert events[-1]["type"] == "done", events
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT content FROM messages WHERE role='assistant'") == "persisted reply"
        assert await conn.fetchval("SELECT message_count FROM ai_agents WHERE id=$1", agent_id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["statement", "commit"])
async def test_failed_write_or_commit_never_reports_done(agent_database, failure):
    pool, agent_id, project = agent_database
    async with pool.acquire() as conn:
        if failure == "statement":
            await conn.execute("ALTER TABLE messages ADD CHECK(role <> 'assistant')")
        else:
            await conn.execute("CREATE TABLE allowed_content(content TEXT PRIMARY KEY); INSERT INTO allowed_content VALUES('hello'); ALTER TABLE messages ADD FOREIGN KEY(content) REFERENCES allowed_content(content) DEFERRABLE INITIALLY DEFERRED")
    response = await response_for(agent_id, project)
    events = [json.loads(frame.removeprefix("data: ")) async for frame in response.body_iterator]
    assert events[-1]["type"] == "error", events
    assert not any(event["type"] == "done" for event in events)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM messages WHERE role='assistant'") == 0
        assert await conn.fetchval("SELECT message_count FROM ai_agents WHERE id=$1", agent_id) == 0
        assert await conn.fetchval("SELECT count(*) FROM messages WHERE role='user'") == 1
