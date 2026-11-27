"""Design Studio text-to-image endpoint — no live provider calls."""
import base64

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import design


async def _no_quota(request):
    return None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(design, "ai_rate_limit", lambda request: None)
    monkeypatch.setattr(design, "check_org_quota", _no_quota)
    app = FastAPI()
    app.include_router(design.router)
    return TestClient(app)


def _stub(monkeypatch, response=None, error=None):
    calls = []

    async def fake(api_key, payload):
        calls.append((api_key, payload))
        if error:
            raise error
        return response

    monkeypatch.setattr(design, "_request_image", fake)
    return calls


def test_missing_key_is_a_clear_503(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = _stub(monkeypatch)
    r = client.post("/api/ai/image/generate", json={"prompt": "a calm study desk"})
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]
    assert calls == []


def test_returns_png_data_urls_and_picks_size_from_aspect(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    png = base64.b64encode(b"\x89PNG fake").decode()
    calls = _stub(monkeypatch, httpx.Response(200, json={"data": [{"b64_json": png}]}))
    r = client.post("/api/ai/image/generate",
                    json={"prompt": "a calm study desk", "width": 1920, "height": 1080})
    assert r.status_code == 200
    assert r.json() == {"images": [f"data:image/png;base64,{png}"]}
    api_key, payload = calls[0]
    assert api_key == "sk-test"
    assert payload["size"] == "1792x1024" and payload["response_format"] == "b64_json"
    assert payload["prompt"] == "a calm study desk"


@pytest.mark.parametrize("width,height,size", [(1024, 1024, "1024x1024"), (1080, 1920, "1024x1792"), (None, None, "1024x1024")])
def test_size_mapping(width, height, size):
    assert design._image_size(width, height) == size


def test_provider_refusal_and_failures_are_safe(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _stub(monkeypatch, httpx.Response(400, json={"error": {"message": "policy sk-test"}}))
    r = client.post("/api/ai/image/generate", json={"prompt": "something odd"})
    assert r.status_code == 422 and "sk-test" not in r.text

    _stub(monkeypatch, httpx.Response(500, text="boom"))
    assert client.post("/api/ai/image/generate", json={"prompt": "a desk"}).status_code == 502

    _stub(monkeypatch, error=httpx.ConnectError("down"))
    assert client.post("/api/ai/image/generate", json={"prompt": "a desk"}).status_code == 502

    _stub(monkeypatch, httpx.Response(200, json={"unexpected": True}))
    assert client.post("/api/ai/image/generate", json={"prompt": "a desk"}).status_code == 502


def test_prompt_is_validated(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls = _stub(monkeypatch)
    assert client.post("/api/ai/image/generate", json={"prompt": "a"}).status_code == 422
    assert calls == []
