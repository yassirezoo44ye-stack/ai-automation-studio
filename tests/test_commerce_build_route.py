import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import build
from app.core.commerce_builder import store_plan


class Pool:
    @asynccontextmanager
    async def acquire(self):
        class Connection:
            execute = AsyncMock()
        yield Connection()


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    app.include_router(build.router)
    with patch.object(build, 'get_pool', return_value=Pool()), patch.object(build, 'owner_user_id', AsyncMock(return_value=uuid.uuid4())), patch.object(build, 'resolve_project_id', AsyncMock()), patch.object(build, 'workspace', return_value=tmp_path), patch.object(build, '_is_dev_account', return_value=True), patch.object(build, 'ai_rate_limit'), patch.object(build, 'InferenceEngine') as engine:
        yield TestClient(app), tmp_path, engine


def test_reviewed_store_build_is_real_files_without_mock_or_model(api):
    client, folder, engine = api
    plan = client.post('/api/build/plan', json={'prompt':'ابني متجر إلكتروني'}).json()['plan']
    assert plan == store_plan()
    response = client.post('/api/build/stream', json={'project_id':str(uuid.uuid4()),'prompt':'ابني متجر إلكتروني','plan':plan})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert response.status_code == 200
    assert any(e['type']=='done' for e in events), events[-2:]
    assert (folder/'main.py').exists() and (folder/'assets/app.js').exists()
    assert 'CREATE TABLE' in (folder/'main.py').read_text()
    engine.assert_not_called()


def test_old_or_modified_plan_is_not_silently_replaced(api):
    client, folder, engine = api
    old = store_plan() | {'tech_stack':{'frontend':'React','backend':'Express','database':'MongoDB'}}
    response = client.post('/api/build/stream',json={'project_id':str(uuid.uuid4()),'prompt':'Build an online store','plan':old})
    assert response.status_code==409
    assert not (folder/'main.py').exists()
    engine.assert_not_called()


def test_custom_existing_files_are_preserved(api):
    client, folder, _ = api
    (folder/'main.py').write_text('# user work')
    response = client.post('/api/build/stream',json={'project_id':str(uuid.uuid4()),'prompt':'Build an online store','plan':store_plan()})
    assert response.status_code==409
    assert (folder/'main.py').read_text()=='# user work'


def test_setup_token_requires_project_ownership_before_filesystem_access(api):
    from fastapi import HTTPException
    client, folder, _ = api
    private = folder/'data'/'owner-setup.txt'
    private.parent.mkdir()
    private.write_text('x'*43)
    with patch.object(build, '_require_project_owner', AsyncMock(side_effect=HTTPException(404, 'Project not found'))), patch.object(build, 'workspace') as workspace:
        assert client.get('/api/projects/other/store-setup').status_code==404
        workspace.assert_not_called()
    with patch.object(build, '_require_project_owner', AsyncMock()):
        response=client.get('/api/projects/own/store-setup')
        assert response.json()=={'token':'x'*43}
        assert response.headers['cache-control']=='no-store'


def test_reopening_completed_store_restores_its_delivery_contract(api):
    from app.core.commerce_builder import store_files
    client, folder, _ = api
    for name, content in store_files().items():
        dest=folder/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    with patch.object(build,'_require_project_owner',AsyncMock()),patch.object(build.process_mgr,'get_running',return_value=None):
        response=client.get('/api/projects/own/commerce')
    assert response.status_code==200
    assert response.json()['running'] is False
    assert response.json()['files']==len(store_files())


def test_owner_generation_uses_real_provider_and_rejects_partial_business_app(api):
    client, _, engine = api

    async def chunks(*args, **kwargs):
        yield {'type': 'delta', 'text': '<<<FILE: index.html>>>\n<h1>CRM</h1>\n<<<ENDFILE>>>\n<<<META>>>\n{"run_command":"serve ."}\n<<<ENDMETA>>>\n'}

    engine.return_value.stream.side_effect = chunks
    with patch('app.services.app_builder.get_app_builder_service', side_effect=RuntimeError('spec unavailable')), patch('app.ai.providers.dev_mock.DevMockProvider') as mock_provider:
        response = client.post('/api/build/stream', json={'project_id':str(uuid.uuid4()), 'prompt':'Build a CRM'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    engine.return_value.stream.assert_called_once()
    mock_provider.assert_not_called()
    assert not any(e['type']=='done' for e in events)
    assert any(e['type']=='error' and 'backend' in e['message'] for e in events)


def test_truncated_stream_never_announces_completion(api):
    client, _, engine = api

    async def chunks(*args, **kwargs):
        yield {'type':'delta', 'text':'<<<FILE: main.py>>>\nprint(1)\n<<<ENDFILE>>>\n<<<META>>>\n{"run_command":"python main.py"}\n'}

    engine.return_value.stream.side_effect = chunks
    with patch('app.services.app_builder.get_app_builder_service', side_effect=RuntimeError('spec unavailable')):
        response=client.post('/api/build/stream', json={'project_id':str(uuid.uuid4()),'prompt':'A simple Python script'})
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert not any(e['type']=='done' for e in events)
    assert any(e['type']=='error' and 'incomplete' in e['message'] for e in events)
