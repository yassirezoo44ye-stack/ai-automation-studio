from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.agents.base import AgentResult
from app.routers import planning_api as api


@pytest.mark.asyncio
async def test_cached_plans_do_not_cross_users_or_orgs(monkeypatch):
    api._plan_cache.clear()
    api._remember('owner-a', 'org-a', 'plan-a', {'goal': 'private'})
    monkeypatch.setattr(api, '_scope', AsyncMock(return_value=('owner-b', 'org-a')))
    with pytest.raises(HTTPException) as error:
        await api.get_plan('plan-a', MagicMock())
    assert error.value.status_code == 404
    monkeypatch.setattr(api, '_scope', AsyncMock(return_value=('owner-a', 'org-b')))
    with pytest.raises(HTTPException):
        await api.get_plan('plan-a', MagicMock())
    monkeypatch.setattr(api, '_scope', AsyncMock(return_value=('owner-a', 'org-a')))
    assert (await api.get_plan('plan-a', MagicMock()))['goal'] == 'private'
    api._plan_cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize('approval', [True, False])
async def test_execute_uses_exact_validated_tasks_and_preserves_context(monkeypatch, approval):
    monkeypatch.setattr(api, '_scope', AsyncMock(return_value=('owner-a', 'org-a')))
    kernel = MagicMock()
    kernel.visible_agents.return_value = [SimpleNamespace(name='analyze')]
    kernel.run = AsyncMock(return_value=AgentResult.ok('analyze', 'review'))
    task = SimpleNamespace(id='one', description='analyze project', agent_name='analyze', depends_on=[])
    plan = SimpleNamespace(plan_id='test', is_safe=True, requires_approval=approval,
                           tasks=[task], parallel_groups=[['one']], to_dict=lambda: {'plan_id': 'test'})
    engine = MagicMock()
    engine.plan.return_value = plan
    engine.validate_plan.return_value = []
    with patch('app.agents.kernel.get_agent_kernel', return_value=kernel), \
         patch('app.planning.engine.get_planning_engine', return_value=engine):
        result = await api.plan_execute(api.PlanRequest(goal='analyze project'), MagicMock())
    if approval:
        assert result['executed'] is False
        kernel.run.assert_not_called()
    else:
        assert result['execution']['success'] is True
        kernel.run.assert_awaited_once_with('analyze project', caller='api', user_id='owner-a',
                                          project_id=None, organization_id='org-a', forced_intent='analyze')
    kernel.plan_and_run.assert_not_called()
    assert list(engine.plan.call_args.kwargs['agents']) == ['analyze']
    api._plan_cache.clear()
