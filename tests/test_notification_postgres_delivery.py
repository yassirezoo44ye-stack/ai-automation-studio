"""REST -> real NotificationService -> PostgreSQL, using an isolated test schema."""
import os
import uuid

import asyncpg
from fastapi import FastAPI, Header
import httpx
import pytest
import pytest_asyncio

from app.core.notifications.service import NotificationService
from app.routers import notifications
from app.tenancy.schema import init_tenancy_schema


@pytest_asyncio.fixture
async def inbox(monkeypatch):
    dsn = os.getenv('NOTIFICATION_TEST_DATABASE_URL') or os.getenv('STUDY_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('A dedicated notification/study test PostgreSQL URL is required')
    schema = 'notification_delivery_' + uuid.uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA {schema}')
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, server_settings={'search_path': schema})
    try:
        async with pool.acquire() as conn:
            await conn.execute('CREATE TABLE users (id UUID PRIMARY KEY)')
            await init_tenancy_schema(conn)
            owners = [str(uuid.uuid4()), str(uuid.uuid4())]
            for owner in owners:
                await conn.execute('INSERT INTO users(id) VALUES($1)', uuid.UUID(owner))
        service = NotificationService(pool)
        monkeypatch.setattr(notifications, 'get_notification_service', lambda: service)
        app = FastAPI()
        app.include_router(notifications.router)

        async def identity(x_test_user: str = Header()):
            assert x_test_user in owners
            return {'id': x_test_user}

        app.dependency_overrides[notifications.get_current_user] = identity
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, service, owners
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA {schema} CASCADE')
        await admin.close()


@pytest.mark.asyncio
async def test_action_json_and_read_state_survive_rest_round_trips(inbox):
    client, service, (owner, _) = inbox
    action = {'label':'View run', 'href':'/automation?run=verified-run'}
    item = await service.create(user_id=owner, type_='workflow.completed', title='Run complete', message='Saved', action=action)
    headers = {'X-Test-User': owner}
    response = await client.get('/api/notifications', headers=headers)
    assert response.status_code == 200
    assert response.json()['notifications'][0]['action'] == action
    assert item['action'] == action
    assert (await client.post(f'/api/notifications/{item["id"]}/read', headers=headers)).status_code == 200
    assert (await client.get('/api/notifications/unread-count', headers=headers)).json()['unread_count'] == 0
    assert (await client.get('/api/notifications', headers=headers)).json()['notifications'][0]['read_status'] is True


@pytest.mark.asyncio
async def test_preferences_are_saved_and_reloaded_from_postgres(inbox):
    client, service, (owner, other) = inbox
    headers = {'X-Test-User': owner}
    response = await client.put('/api/notifications/preferences', headers=headers, json={'muted_categories':['workflow','agent']})
    assert response.status_code == 200
    assert await service.get_preferences(user_id=owner) == ['workflow', 'agent']
    assert (await client.get('/api/notifications/preferences', headers=headers)).json()['muted_categories'] == ['workflow','agent']
    assert await service.get_preferences(user_id=other) == []
    invalid = await client.put('/api/notifications/preferences', headers=headers, json={'muted_categories':['invalid']})
    assert invalid.status_code == 400
    assert await service.get_preferences(user_id=owner) == ['workflow', 'agent']


@pytest.mark.asyncio
async def test_notification_mutations_remain_owner_scoped(inbox):
    client, service, (owner, other) = inbox
    item = await service.create(user_id=owner, type_='system', title='Private', message='Only owner')
    foreign = {'X-Test-User': other}
    assert (await client.get('/api/notifications', headers=foreign)).json()['notifications'] == []
    for suffix in ('read', 'archive'):
        assert (await client.post(f'/api/notifications/{item["id"]}/{suffix}', headers=foreign)).status_code == 404
    assert (await client.delete(f'/api/notifications/{item["id"]}', headers=foreign)).status_code == 404
    assert await service.unread_count(user_id=owner) == 1
    assert (await client.delete(f'/api/notifications/{item["id"]}', headers={'X-Test-User':owner})).status_code == 204
    assert await service.list(user_id=owner) == []
