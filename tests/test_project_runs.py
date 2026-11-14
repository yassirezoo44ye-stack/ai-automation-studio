"""Durable run queue tests against PostgreSQL; no real paid model calls."""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.base import AgentResult
from app.core.project_runs import ProjectRunWorker, expire_leases
from tests.test_project_plans import harness as _project_harness, payload, ORG_A, ORG_B

harness = _project_harness


def request_body(runner='skill'):
    return {'request_id': str(uuid.uuid4()), 'approved': True, 'runner': runner,
            'skill_id': 'flow-project-planning' if runner == 'skill' else None}


async def make_plan(client):
    return (await client.post('/api/project-plans', json=payload())).json()


@pytest.mark.asyncio
async def test_explicit_approval_idempotency_and_dependency_guards(harness):
    client, pool = harness
    plan = await make_plan(client)
    path = '/api/project-plans/' + plan['id'] + '/tasks/scope/runs'
    body = request_body()
    assert (await client.post(path, json={**body, 'approved': False})).status_code == 422
    assert (await client.post(path, json={**body, 'skill_id': '../unsafe'})).status_code == 422
    first, replay = await asyncio.gather(client.post(path, json=body), client.post(path, json=body))
    assert first.status_code == replay.status_code == 202, (first.text, replay.text)
    assert first.json()['id'] == replay.json()['id']
    assert (await client.post(path, json=request_body())).status_code == 409
    assert (await client.put('/api/tasks/' + plan['tasks'][0]['task_id'], json={'status': 'done'})).status_code == 409
    assert (await client.delete('/api/tasks/' + plan['tasks'][0]['task_id'])).status_code == 409
    assert (await client.post(path.replace('/scope/', '/build/'), json=request_body())).status_code == 409
    async with pool.acquire() as conn:
        assert await conn.fetchval('SELECT COUNT(*) FROM project_task_runs') == 1


@pytest.mark.asyncio
async def test_result_survives_new_worker_and_artifact_is_private(harness):
    client, pool = harness
    client.headers['x-test-org'] = str(ORG_A)
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    execute = AsyncMock(return_value=AgentResult.ok('flow-project-planning', 'A real test deliverable' + chr(0)))
    worker = ProjectRunWorker(pool, execute=execute)
    worker.authorized = AsyncMock(return_value=True)
    row = await worker.claim()
    assert await ProjectRunWorker(pool).claim() is None
    await worker.perform(row)
    detail = (await client.get(root + '/runs/' + run['id'])).json()
    assert detail['status'] == 'completed' and detail['output'] == 'A real test deliverable' + chr(0xfffd)
    assert detail['acceptance_verified'] is False
    artifact = await client.get(root + '/runs/' + run['id'] + '/artifact')
    assert artifact.status_code == 200 and artifact.text == detail['output']
    assert 'attachment' in artifact.headers['content-disposition']
    assert (await client.get(root)).json()['tasks'][0]['status'] == 'in_progress'
    assert (await client.put(root + '/tasks/scope', json={'status': 'done'})).status_code == 200
    client.headers['x-test-org'] = str(ORG_B)
    assert (await client.get(root + '/runs')).status_code == 404
    assert (await client.get(root + '/runs/' + run['id'] + '/artifact')).status_code == 404
    client.headers['x-test-org'] = str(ORG_A)
    client.headers['x-test-user'] = 'b'
    assert (await client.get(root + '/runs/' + run['id'])).status_code == 404


@pytest.mark.asyncio
async def test_cancel_before_dispatch_and_expired_lease_never_replay(harness):
    client, pool = harness
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    assert (await client.delete(root + '/runs/' + run['id'])).json()['status'] == 'cancelled'
    assert (await client.delete(root + '/runs/' + run['id'])).status_code == 200
    worker = ProjectRunWorker(pool, execute=AsyncMock())
    assert await worker.claim() is None
    fresh = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    row = await worker.claim()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE project_task_runs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=$1", uuid.UUID(fresh['id']))
        await expire_leases(conn)
    restarted = ProjectRunWorker(pool)
    assert await restarted.claim() is None
    assert (await client.get(root + '/runs/' + fresh['id'])).json()['status'] == 'interrupted'
    worker.authorized = AsyncMock(return_value=True)
    await worker.perform(row)
    assert (await client.get(root + '/runs/' + fresh['id'])).json()['status'] == 'interrupted'
    worker.execute.assert_not_called()


@pytest.mark.asyncio
async def test_running_cancel_discards_late_result(harness):
    client, pool = harness
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    started = asyncio.Event()
    async def execute(row):
        started.set()
        await asyncio.sleep(10)
        return AgentResult.ok('test', 'must not persist')
    worker = ProjectRunWorker(pool, execute=execute)
    row = await worker.claim()
    operation = asyncio.create_task(worker.perform(row))
    await asyncio.wait_for(started.wait(), timeout=3)
    assert (await client.delete(root + '/runs/' + run['id'])).status_code == 200
    await asyncio.wait_for(operation, timeout=4)
    detail = (await client.get(root + '/runs/' + run['id'])).json()
    assert detail['status'] == 'cancelled' and detail['output'] is None


@pytest.mark.asyncio
async def test_failed_agent_and_revoked_authorization_are_not_success(harness):
    client, pool = harness
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    execute = AsyncMock(return_value=AgentResult.fail('test', 'raw provider sensitive details'))
    worker = ProjectRunWorker(pool, execute=execute)
    await worker.perform(await worker.claim())
    detail = (await client.get(root + '/runs/' + run['id'])).json()
    assert detail['status'] == 'failed' and 'sensitive' not in detail['error']
    assert (await client.get(root + '/runs/' + run['id'] + '/artifact')).status_code == 409
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    worker.authorized = AsyncMock(return_value=False)
    execute.reset_mock()
    await worker.perform(await worker.claim())
    execute.assert_not_called()
    assert (await client.get(root + '/runs/' + run['id'])).json()['status'] == 'failed'


@pytest.mark.asyncio
async def test_worker_passes_only_verified_snapshot_and_forced_agent(harness):
    client, pool = harness
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    await client.post(root + '/tasks/scope/runs', json=request_body('inspect_project'))
    worker = ProjectRunWorker(pool)
    row = await worker.claim()
    kernel = type('Kernel', (), {'run': AsyncMock(return_value=AgentResult.ok('inspect_project', 'report'))})()
    with patch('app.agents.kernel.get_agent_kernel', return_value=kernel):
        await worker.execute_agent(row)
    call = kernel.run.call_args
    assert call.kwargs['forced_intent'] == 'inspect_project'
    assert call.kwargs['project_id'] == plan['project_id']
    assert call.kwargs['user_id'] == str(row['user_id'])
    assert call.kwargs['run_id'] == str(row['id'])


@pytest.mark.asyncio
async def test_graceful_worker_shutdown_records_interruption(harness):
    client, pool = harness
    plan = await make_plan(client)
    root = '/api/project-plans/' + plan['id']
    run = (await client.post(root + '/tasks/scope/runs', json=request_body())).json()
    entered = asyncio.Event()
    async def execute(row):
        entered.set()
        await asyncio.sleep(20)
        return AgentResult.ok('test', 'not accepted after shutdown')
    worker = ProjectRunWorker(pool, execute=execute)
    await worker.start()
    await asyncio.wait_for(entered.wait(), timeout=3)
    await worker.stop()
    assert (await client.get(root + '/runs/' + run['id'])).json()['status'] == 'interrupted'
    assert await ProjectRunWorker(pool).claim() is None


@pytest.mark.asyncio
async def test_concurrent_runs_respect_user_capacity(harness):
    client, pool = harness
    plans = [await make_plan(client) for _ in range(4)]
    responses = await asyncio.gather(*[client.post('/api/project-plans/' + plan['id'] + '/tasks/scope/runs', json=request_body()) for plan in plans])
    assert sorted(response.status_code for response in responses) == [202, 202, 202, 429]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM project_task_runs WHERE status='queued'") == 3


@pytest.mark.asyncio
async def test_start_does_not_reopen_task_completed_while_waiting_for_lock(harness):
    client, pool = harness
    plan = await make_plan(client)
    async with pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        await conn.fetchval('SELECT id FROM project_plans WHERE id=$1 FOR UPDATE', uuid.UUID(plan['id']))
        await conn.execute("UPDATE tasks SET status='done' WHERE id=$1", uuid.UUID(plan['tasks'][0]['task_id']))
        starting = asyncio.create_task(client.post('/api/project-plans/' + plan['id'] + '/tasks/scope/runs', json=request_body()))
        await asyncio.sleep(0.05)
        await transaction.commit()
    assert (await starting).status_code == 409
    assert (await client.get('/api/project-plans/' + plan['id'])).json()['tasks'][0]['status'] == 'done'
