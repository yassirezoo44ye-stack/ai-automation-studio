"""AgentOS skill registration, API routing, isolation and model requests."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.builtin.flow_skills import FlowSkillAgent, register
from app.ai.models import CompletionResponse, ToolCall
from app.core.ai.skills import SKILL_IDS
from app.routers.agent_os_api import RunRequest, agentos_run
from tests.test_agent_os import _make_kernel


@pytest.mark.asyncio
@pytest.mark.parametrize('skill_id', SKILL_IDS)
async def test_kernel_routes_all_skills_with_verified_context(skill_id):
    kernel = _make_kernel()
    register(kernel)
    assert set(SKILL_IDS).issubset(kernel.visible_agent_names('org-a'))
    assert kernel._agent_owners.owner_of(skill_id) is None
    with patch('app.agents.builtin.flow_skills.get_pool', return_value=None), \
         patch('app.agents.builtin.flow_skills.InferenceEngine.complete',
               AsyncMock(return_value=CompletionResponse(content='draft'))) as complete:
        result = await kernel.run('Prepare a draft', forced_intent=skill_id,
                                  user_id='user-a', organization_id='org-a')
    assert result.success
    assert result.data == {'skill_id': skill_id, 'mode': 'advisory', 'tools_enabled': False}
    call = complete.call_args
    assert skill_id in call.args[0].system
    assert call.args[0].tools is None
    assert call.args[0].memory_enabled is False
    assert call.kwargs == {'user_id': 'user-a', 'org_id': 'org-a', 'auto_tools': False}
    assert kernel._memory.recent(1, org_id='org-b') == []


@pytest.mark.asyncio
async def test_no_user_cannot_call_provider_and_no_tool_request_executes():
    kernel = _make_kernel()
    register(kernel)
    with patch('app.agents.builtin.flow_skills.InferenceEngine.complete', AsyncMock()) as complete:
        result = await kernel.run('draft', forced_intent=SKILL_IDS[0])
        assert not result.success
        complete.assert_not_called()
    response = CompletionResponse(tool_calls=[ToolCall(id='x', name='delete_file', arguments={})])
    with patch('app.agents.builtin.flow_skills.get_pool', return_value=None), \
         patch('app.agents.builtin.flow_skills.InferenceEngine.complete', AsyncMock(return_value=response)):
        result = await kernel.run('draft', forced_intent=SKILL_IDS[0], user_id='user-a')
    assert not result.success
    assert result.error == 'Skill requested unavailable tools'
    assert not FlowSkillAgent(SKILL_IDS[0]).permissions.can_execute_subprocess
    assert not FlowSkillAgent(SKILL_IDS[0]).permissions.can_write_filesystem


@pytest.mark.asyncio
async def test_api_selects_skill_and_ignores_client_identity():
    kernel = _make_kernel()
    register(kernel)
    req = RunRequest(input='draft', skill_id=SKILL_IDS[0], user_id='spoofed', organization_id='spoofed')
    with patch('app.agents.kernel.get_agent_kernel', return_value=kernel), \
         patch('app.tenancy.context.optional_user_id', AsyncMock(return_value='verified-user')), \
         patch('app.tenancy.context.optional_org_id', AsyncMock(return_value='verified-org')), \
         patch('app.agents.builtin.flow_skills.get_pool', return_value=None), \
         patch('app.agents.builtin.flow_skills.InferenceEngine.complete',
               AsyncMock(return_value=CompletionResponse(content='draft'))) as complete:
        result = await agentos_run(req, MagicMock())
    assert result['success']
    assert complete.call_args.kwargs['user_id'] == 'verified-user'
    assert complete.call_args.kwargs['org_id'] == 'verified-org'
    with pytest.raises(ValidationError):
        RunRequest(input='draft', skill_id='../README')
    with patch('app.agents.kernel.get_agent_kernel', return_value=kernel), \
         patch('app.tenancy.context.optional_user_id', AsyncMock(return_value=None)), \
         patch('app.tenancy.context.optional_org_id', AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as error:
            await agentos_run(req, MagicMock())
    assert error.value.status_code == 401


def test_builtin_loader_discovers_all_skills():
    from app.agents.loader import load_file
    kernel = _make_kernel()
    assert load_file(Path('app/agents/builtin/flow_skills.py').resolve(), kernel)
    assert set(kernel.visible_agent_names(None)) == set(SKILL_IDS)


@pytest.mark.asyncio
async def test_planner_system_contains_skill_and_scopes_agent_names(monkeypatch):
    from app.agents.base import AgentContext
    from app.agents.builtin.plan_agent import PlanAgent
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only')
    kernel = _make_kernel()
    kernel.register_agent(FlowSkillAgent(SKILL_IDS[0]))
    kernel.register_agent(FlowSkillAgent(SKILL_IDS[1]), owner='other-org')
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text=f'{SKILL_IDS[0]} draft')],
        usage=MagicMock(input_tokens=1, output_tokens=1),
    ))
    with patch('anthropic.AsyncAnthropic', return_value=client), \
         patch('app.core.org_quota.check_org_quota_id', AsyncMock(return_value=True)), \
         patch('app.core.org_quota.record_org_tokens', AsyncMock()):
        result = await PlanAgent().run(AgentContext(
            input='plan draft', args='draft', kernel=kernel, memory=kernel._memory,
            organization_id='own-org', user_id='user',
        ))
    assert result.success
    call = client.messages.create.call_args.kwargs
    assert 'flow-project-planning' in call['system']
    assert SKILL_IDS[1] not in call['messages'][0]['content']
