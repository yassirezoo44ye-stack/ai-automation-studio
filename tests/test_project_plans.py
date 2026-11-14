"""Real-Postgres tests: persistence, idempotency, rollback, ownership and task graph."""
import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, patch

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.core import db
from app.core.project_plans import init_schema
from app.routers import project_plans as api
from app.routers import tasks
from app.routers import project_runs as runs_api


DRAFT = {'title': 'Launch Flow CRM', 'goal': 'Build a CRM for a small team', 'tasks': [
    {'key': 'scope', 'title': 'Define the scope', 'acceptance': ['Three user journeys approved'], 'depends_on': [], 'priority': 'high'},
    {'key': 'build', 'title': 'Build the first journey', 'acceptance': ['Saved data survives reload'], 'depends_on': ['scope'], 'priority': 'medium'},
]}
TEST_DSN = os.getenv('PROJECT_PLAN_TEST_DATABASE_URL') or os.getenv('STUDY_TEST_DATABASE_URL')
USER_A = uuid.UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
USER_B = uuid.UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
ORG_A = uuid.UUID('11111111-1111-4111-8111-111111111111')
ORG_B = uuid.UUID('22222222-2222-4222-8222-222222222222')


def test_graph_and_draft_validation():
    assert len(api.PlanDraft.model_validate(DRAFT).tasks) == 2
    for invalid in [
        {**DRAFT, 'tasks': [DRAFT['tasks'][0], DRAFT['tasks'][0]]},
        {**DRAFT, 'tasks': [{**DRAFT['tasks'][0], 'depends_on': ['missing']}]},
        {**DRAFT, 'tasks': [{**DRAFT['tasks'][0], 'depends_on': ['build']}, DRAFT['tasks'][1]]},
        {**DRAFT, 'tasks': [{**DRAFT['tasks'][0], 'acceptance': [' ']}]},
    ]:
        with pytest.raises(ValidationError):
            api.PlanDraft.model_validate(invalid)


@pytest_asyncio.fixture
async def harness(monkeypatch):
    dsn = TEST_DSN
    if not dsn:
        pytest.skip('Set PROJECT_PLAN_TEST_DATABASE_URL for the real PostgreSQL tests')
    schema = 'plan_test_' + uuid.uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA {schema}')
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5,
                                    server_settings={'search_path': f'{schema},public'})
    monkeypatch.setattr(db, 'get_pool', lambda: pool)
    monkeypatch.setattr(api, 'get_pool', lambda: pool)
    monkeypatch.setattr(tasks, 'get_pool', lambda: pool)
    monkeypatch.setattr(runs_api, 'get_pool', lambda: pool)
    async with pool.acquire() as conn:
        await db.init_db(conn)
    await db.ensure_tasks_table()
    async with pool.acquire() as conn:
        await init_schema(conn)
        await init_schema(conn)
        await conn.execute('INSERT INTO users(id,email) VALUES($1,$2),($3,$4)', USER_A, 'a@flow.test', USER_B, 'b@flow.test')

    async def user(conn, request):
        header = request.headers.get('x-test-user')
        if header not in ('a', 'b'):
            raise HTTPException(401, 'Sign in')
        return USER_A if header == 'a' else USER_B
    def email(request):
        return request.headers.get('x-test-user', 'a') + '@flow.test'
    async def org(request):
        return request.headers.get('x-test-org')
    monkeypatch.setattr(api, 'owner_user_id', user)
    monkeypatch.setattr(api, 'owner_email', email)
    monkeypatch.setattr(tasks, 'owner_email', email)
    monkeypatch.setattr(runs_api, 'owner_email', email)
    monkeypatch.setattr(runs_api, 'ai_rate_limit', lambda request: None)
    monkeypatch.setattr(tasks, 'owner_user_id', user)
    monkeypatch.setattr('app.tenancy.context.optional_org_id', org)
    application = FastAPI()
    application.include_router(api.router)
    application.include_router(runs_api.router)
    application.include_router(tasks.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://test', headers={'x-test-user': 'a'})
    try:
        yield client, pool
    finally:
        await client.aclose()
        await pool.close()
        await admin.execute(f'DROP SCHEMA {schema} CASCADE')
        await admin.close()


def payload():
    return {'request_id': str(uuid.uuid4()), 'draft': DRAFT}


@pytest.mark.asyncio
async def test_create_reopen_and_idempotent_concurrent_save(harness):
    client, pool = harness
    body = payload()
    first, second = await asyncio.gather(client.post('/api/project-plans', json=body), client.post('/api/project-plans', json=body))
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json()['id'] == second.json()['id']
    plan = first.json()
    async with pool.acquire() as conn:
        assert await conn.fetchval('SELECT count(*) FROM project_plans') == 1
        assert await conn.fetchval("SELECT count(*) FROM tasks WHERE source='project_plan'") == 2
    # Independent client/session reads PostgreSQL, not an in-process cache.
    async with httpx.AsyncClient(transport=client._transport, base_url='http://test', headers={'x-test-user': 'a'}) as new_session:
        assert (await new_session.get('/api/project-plans/' + plan['id'])).json()['tasks'] == plan['tasks']
    changed = {**body, 'draft': {**DRAFT, 'title': 'Different plan'}}
    assert (await client.post('/api/project-plans', json=changed)).status_code == 409
    assert (await client.get('/api/project-plans')).json()['plans'][0]['id'] == plan['id']


@pytest.mark.asyncio
async def test_user_org_and_project_isolation(harness):
    client, pool = harness
    client.headers['x-test-org'] = str(ORG_A)
    body = payload()
    saved = (await client.post('/api/project-plans', json=body)).json()
    client.headers['x-test-user'] = 'b'
    assert (await client.get('/api/project-plans/' + saved['id'])).status_code == 404
    assert (await client.get('/api/project-plans')).json() == {'plans': []}
    assert (await client.post('/api/project-plans', json={**payload(), 'project_id': saved['project_id']})).status_code == 404
    client.headers['x-test-user'] = 'a'
    client.headers['x-test-org'] = str(ORG_B)
    assert (await client.get('/api/project-plans/' + saved['id'])).status_code == 404
    assert (await client.post('/api/project-plans', json=body)).status_code == 409
    client.headers.pop('x-test-user')
    assert (await client.get('/api/project-plans')).status_code == 401


@pytest.mark.asyncio
async def test_task_dependencies_and_legacy_api_cannot_bypass(harness):
    client, pool = harness
    saved = (await client.post('/api/project-plans', json=payload())).json()
    root = '/api/project-plans/' + saved['id'] + '/tasks/'
    assert (await client.put(root + 'build', json={'status': 'done'})).status_code == 409
    legacy = '/api/tasks/' + saved['tasks'][1]['task_id']
    assert (await client.put(legacy, json={'status': 'done'})).status_code == 409
    assert (await client.put(root + 'scope', json={'status': 'done'})).status_code == 200
    assert (await client.put(legacy, json={'status': 'done'})).status_code == 200
    assert (await client.get('/api/project-plans/' + saved['id'])).json()['completed'] == 2
    assert (await client.put(root + 'scope', json={'status': 'pending'})).status_code == 409
    assert (await client.put(root + 'build', json={'status': 'pending'})).status_code == 200
    assert (await client.put(root + 'scope', json={'status': 'pending'})).status_code == 200
    assert (await client.put(root + 'absent', json={'status': 'done'})).status_code == 404


@pytest.mark.asyncio
async def test_atomic_rollback_on_failure(harness):
    client, pool = harness
    with patch.object(api, 'plan_detail', AsyncMock(side_effect=HTTPException(503, 'test failure'))):
        result = await client.post('/api/project-plans', json=payload())
    assert result.status_code == 503
    async with pool.acquire() as conn:
        assert await conn.fetchval('SELECT count(*) FROM project_plans') == 0
        assert await conn.fetchval("SELECT count(*) FROM tasks WHERE source='project_plan'") == 0
        assert await conn.fetchval('SELECT count(*) FROM projects WHERE user_id=$1', USER_A) == 0


@pytest.mark.asyncio
async def test_draft_provider_output_validated_and_not_saved(harness, monkeypatch):
    client, pool = harness
    from app.ai.models import CompletionResponse
    monkeypatch.setattr(api, 'ai_rate_limit', lambda request: None)
    with patch.object(api.InferenceEngine, 'complete', AsyncMock(return_value=CompletionResponse(content=json.dumps(DRAFT)))) as complete:
        response = await client.post('/api/project-plans/draft', json={'goal': 'Build a CRM'})
    assert response.status_code == 200
    assert response.json()['saved'] is False and response.json()['executed'] is False
    assert complete.call_args.kwargs['auto_tools'] is False
    assert complete.call_args.args[0].tools is None
    with patch.object(api.InferenceEngine, 'complete', AsyncMock(return_value=CompletionResponse(content='not json'))):
        assert (await client.post('/api/project-plans/draft', json={'goal': 'Build a CRM'})).status_code == 502
    async with pool.acquire() as conn:
        assert await conn.fetchval('SELECT count(*) FROM project_plans') == 0


@pytest.mark.asyncio
async def test_unknown_org_header_does_not_fall_back_to_personal(harness, monkeypatch):
    client, _ = harness
    monkeypatch.setattr('app.tenancy.context.optional_org_id', AsyncMock(return_value=None))
    client.headers['X-Organization-Id'] = str(ORG_B)
    assert (await client.get('/api/project-plans')).status_code == 404
    assert (await client.post('/api/project-plans', json=payload())).status_code == 404


@pytest.mark.asyncio
async def test_deleted_prerequisite_stays_visible_and_blocks_dependents(harness):
    client, _ = harness
    saved = (await client.post('/api/project-plans', json=payload())).json()
    assert (await client.delete('/api/tasks/' + saved['tasks'][0]['task_id'])).status_code == 200
    detail = (await client.get('/api/project-plans/' + saved['id'])).json()
    assert detail['tasks'][0]['status'] == 'deleted'
    assert detail['total'] == (await client.get('/api/project-plans')).json()['plans'][0]['total'] == 2
    assert (await client.put('/api/project-plans/' + saved['id'] + '/tasks/build', json={'status': 'done'})).status_code == 409


@pytest.mark.asyncio
async def test_legacy_task_read_edit_delete_respect_plan_org(harness):
    client, _ = harness
    client.headers['x-test-org'] = str(ORG_A)
    saved = (await client.post('/api/project-plans', json=payload())).json()
    tid = saved['tasks'][0]['task_id']
    assert len((await client.get('/api/tasks')).json()['tasks']) == 2
    client.headers['x-test-org'] = str(ORG_B)
    assert (await client.get('/api/tasks')).json()['tasks'] == []
    assert (await client.put('/api/tasks/' + tid, json={'notes': 'wrong context'})).status_code == 404
    assert (await client.delete('/api/tasks/' + tid)).status_code == 404
    client.headers['x-test-org'] = str(ORG_A)
    assert (await client.put('/api/tasks/' + tid, json={'notes': 'reviewed context'})).status_code == 200
    other = (await client.post('/api/project-plans', json=payload())).json()
    assert (await client.put('/api/tasks/' + tid, json={'project_id': other['project_id']})).status_code == 409
