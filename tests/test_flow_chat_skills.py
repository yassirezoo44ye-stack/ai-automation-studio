from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from pydantic import ValidationError

from app.ai.models import CompletionResponse
from app.routers import chat
from tests.test_ai_gateway_migration_chat_build import _fake_pool, _StreamChunks


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [True, False])
async def test_default_chat_passes_skill_to_budget_and_provider(streaming):
    pool, _ = _fake_pool()
    skill = 'flow-project-planning'
    body = chat.RunRequest(project_id='demo', prompt='Plan', skill_ids=[skill])
    with patch.object(chat, 'get_pool', return_value=pool), \
         patch.object(chat, 'ai_rate_limit'), \
         patch.object(chat, 'check_org_quota', AsyncMock(return_value=None)), \
         patch.object(chat, 'owner_user_id', AsyncMock(return_value=uuid.uuid4())), \
         patch.object(chat, 'resolve_project_id', AsyncMock(return_value=uuid.uuid4())), \
         patch.object(chat, 'record_org_tokens', AsyncMock()), \
         patch.object(chat, 'budget_history', side_effect=lambda history, **kw: history) as budget, \
         patch.object(chat.InferenceEngine, 'stream', return_value=_StreamChunks([
             {'type': 'delta', 'text': 'plan'}, {'type': 'done'},
         ])) as stream, \
         patch.object(chat.InferenceEngine, 'complete', AsyncMock(return_value=CompletionResponse(content='plan'))) as complete:
        if streaming:
            response = await chat.run_stream(body, MagicMock())
            events = [event async for event in response.body_iterator]
            assert any('plan' in event for event in events)
            call = stream.call_args
            assert budget.call_args.kwargs['system'] == call.args[0].system
        else:
            result = await chat.run_agent(body, MagicMock())
            assert result['result']['summary'] == 'plan'
            call = complete.call_args
        assert skill in call.args[0].system
        assert call.args[0].tools is None
        assert call.kwargs['auto_tools'] is False


def test_invalid_chat_skill_rejected():
    with pytest.raises(ValidationError):
        chat.RunRequest(project_id='demo', prompt='Plan', skill_ids=['unknown'])
