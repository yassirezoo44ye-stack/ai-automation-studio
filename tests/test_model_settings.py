"""Ensure saved model choices reach inference and invalid choices are rejected."""
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.ai.models import CompletionResponse, UsageStats
from app.routers import build, chat


@pytest.fixture
def model_api(monkeypatch, tmp_path):
    owner = uuid.uuid4()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            conn = MagicMock()
            conn.execute = AsyncMock()
            conn.fetchval = AsyncMock(return_value=uuid.uuid4())
            conn.fetch = AsyncMock(return_value=[])
            yield conn

    engine = MagicMock()
    payload = {'description':'Script', 'files':[{'path':'main.py','content':'print(1)'}], 'run_command':'python main.py','language':'python'}
    engine.complete = AsyncMock(return_value=CompletionResponse(content=json.dumps(payload), usage=UsageStats(input_tokens=1,output_tokens=1,total_tokens=2,cost_usd=0)))

    async def chunks(*args, **kwargs):
        yield {'type':'delta','text':'<<<FILE: main.py>>>\nprint(1)\n<<<ENDFILE>>>\n<<<META>>>\n{"run_command":"python main.py","language":"python"}\n<<<ENDMETA>>>\n'}

    engine.stream.side_effect = chunks
    for module in (build, chat):
        monkeypatch.setattr(module, 'get_pool', lambda: Pool())
        monkeypatch.setattr(module, 'owner_user_id', AsyncMock(return_value=owner))
        monkeypatch.setattr(module, 'resolve_project_id', AsyncMock(return_value=uuid.uuid4()))
        monkeypatch.setattr(module, 'check_org_quota', AsyncMock(return_value=None))
        monkeypatch.setattr(module, 'record_org_tokens', AsyncMock())
        monkeypatch.setattr(module, 'InferenceEngine', lambda **kwargs: engine)
        monkeypatch.setattr(module, 'ai_rate_limit', lambda *args, **kwargs: None)
    monkeypatch.setattr(build, 'workspace', lambda pid: tmp_path)
    monkeypatch.setattr(build, '_is_dev_account', lambda request: False)
    monkeypatch.setattr('app.services.app_builder.get_app_builder_service', MagicMock(side_effect=RuntimeError('spec not part of model test')))
    app = FastAPI()
    app.include_router(build.router)
    app.include_router(chat.router)
    yield TestClient(app), engine


@pytest.mark.parametrize('path,model', [('/api/run','claude-haiku-4-5-20251001'),('/api/build','claude-opus-4-8')])
def test_selected_model_reaches_completion(model_api, path, model):
    client, engine = model_api
    response = client.post(path, json={'project_id':str(uuid.uuid4()),'prompt':'Build a Python script','model':model})
    assert response.status_code == 200, response.text
    assert engine.complete.call_args.args[0].model == model


@pytest.mark.parametrize('path,model', [('/api/run/stream','claude-haiku-4-5-20251001'),('/api/build/stream','claude-opus-4-8')])
def test_selected_model_reaches_streaming_inference(model_api, path, model):
    client, engine = model_api
    response=client.post(path,json={'project_id':str(uuid.uuid4()),'prompt':'Build a Python script','model':model})
    assert response.status_code == 200
    assert '"type": "error"' not in response.text, response.text
    assert engine.stream.call_args.args[0].model == model


@pytest.mark.parametrize('path', ['/api/run','/api/build'])
def test_unknown_model_is_rejected_before_inference(model_api, path):
    client, engine = model_api
    response=client.post(path,json={'project_id':str(uuid.uuid4()),'prompt':'hello','model':'unapproved-model'})
    assert response.status_code == 422
    engine.complete.assert_not_called()


def test_older_clients_keep_the_default_model(model_api):
    client, engine = model_api
    assert client.post('/api/run',json={'project_id':str(uuid.uuid4()),'prompt':'hello'}).status_code == 200
    assert engine.complete.call_args.args[0].model == 'claude-sonnet-4-6'
