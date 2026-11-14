"""Skill loading, API persistence, provider context, and permission boundaries."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from pydantic import ValidationError

from app.core.ai import skills
from app.routers import agents
from tests.test_ai_gateway_migration_agents_design_tasks import _fake_pool, _StreamChunks


def test_catalog_and_traversal_rejection():
    assert len(skills.skill_catalog()) == 9
    assert all(s['title'] and s['description'] for s in skills.skill_catalog())
    for bad in ['../README', '/etc/passwd', 'unknown']:
        with pytest.raises(ValueError):
            skills.load_skill(bad)
    with pytest.raises(ValidationError):
        agents.AgentCreate(name='test', system_prompt='test', skill_ids=['unknown'])
    with pytest.raises(ValueError):
        skills.validate_skill_ids(list(skills.SKILL_IDS[:4]))


def test_loader_rejects_symlink(tmp_path, monkeypatch):
    skills.load_skill.cache_clear()
    folder = tmp_path / skills.SKILL_IDS[0]
    folder.mkdir()
    (folder / 'SKILL.md').symlink_to(Path('README.md').resolve())
    monkeypatch.setattr(skills, 'SKILLS_ROOT', tmp_path)
    with pytest.raises(ValueError):
        skills.load_skill(skills.SKILL_IDS[0])
    skills.load_skill.cache_clear()


@pytest.mark.asyncio
async def test_agent_crud_preserves_omitted_skills_and_allows_clearing():
    pool, conn = _fake_pool()
    uid, aid = uuid.uuid4(), str(uuid.uuid4())
    with patch.object(agents, 'get_pool', return_value=pool), \
         patch.object(agents, 'owner_user_id', AsyncMock(return_value=uid)), \
         patch.object(agents, 'ensure_agents_table', AsyncMock()):
        await agents.create_agent(agents.AgentCreate(name='test', system_prompt='role',
                                  skill_ids=['flow-project-planning']), MagicMock())
        assert conn.fetchval.call_args.args[-1] == ['flow-project-planning']
        await agents.update_agent(aid, agents.AgentUpdate(name='new'), MagicMock())
        assert conn.execute.call_args.args[-1] is None
        assert conn.execute.call_args.args[-2] == uid
        await agents.update_agent(aid, agents.AgentUpdate(skill_ids=[]), MagicMock())
        assert conn.execute.call_args.args[-1] == []


@pytest.mark.asyncio
async def test_catalog_requires_owner_authentication():
    pool, _ = _fake_pool()
    with patch.object(agents, 'get_pool', return_value=pool), \
         patch.object(agents, 'owner_user_id', AsyncMock(side_effect=PermissionError)):
        with pytest.raises(PermissionError):
            await agents.list_agent_skills(MagicMock())


@pytest.mark.asyncio
async def test_chat_skill_reaches_budget_and_provider_without_tools():
    pool, conn = _fake_pool()
    conn.fetchrow.return_value['skill_ids'] = ['flow-career-assistance']
    with patch.object(agents, 'get_pool', return_value=pool), \
         patch.object(agents, 'owner_user_id', AsyncMock(return_value=uuid.uuid4())), \
         patch.object(agents, 'ensure_agents_table', AsyncMock()), \
         patch.object(agents, 'resolve_project_id', AsyncMock(return_value=uuid.uuid4())), \
         patch.object(agents, 'ai_rate_limit'), \
         patch.object(agents, 'check_org_quota', AsyncMock(return_value=None)), \
         patch.object(agents, 'budget_history', side_effect=lambda history, **kw: history) as budget, \
         patch.object(agents.InferenceEngine, 'stream', return_value=_StreamChunks([
             {'type': 'delta', 'text': 'answer'}, {'type': 'done'},
         ])) as stream:
        aid = str(uuid.uuid4())
        response = await agents.agent_chat_stream(aid, agents.AgentChatRequest(agent_id=aid, prompt='jobs'), MagicMock())
        events = [event async for event in response.body_iterator]
        request = stream.call_args.args[0]
        assert 'flow-career-assistance' in request.system
        assert budget.call_args.kwargs['system'] == request.system
        assert request.tools is None
        assert stream.call_args.kwargs['auto_tools'] is False
        assert any('answer' in event for event in events)


@pytest.mark.asyncio
async def test_runtime_run_and_stream_use_skills_without_expanding_tools():
    from app.ai.models import CompletionResponse, UsageStats
    from app.core.ai.agents.runtime import AgentConfig, AgentRuntime
    from app.core.ai.registry.registry import platform_registry

    response = CompletionResponse(content='ok', model='test', provider='openai', usage=UsageStats())
    runtime = AgentRuntime(AgentConfig(name='backend'))
    with patch.object(platform_registry, 'complete_with_events', AsyncMock(return_value=(response, None))) as complete:
        result = await runtime.run('implement')
        assert result.success
        req = complete.call_args.args[0]
        assert 'flow-app-building' in req.system
        assert req.tools is None
    async def chunks(req):
        assert 'flow-app-building' in req.system
        assert req.tools is None
        if False:
            yield None
    with patch.object(platform_registry, 'stream_with_events', side_effect=chunks):
        assert [c async for c in runtime.stream('implement')] == []
    assert skills.compose_skill_system('original', []) == 'original'
