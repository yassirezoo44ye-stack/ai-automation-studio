"""Opaque commerce RPC stays authenticated, bounded and isolated from Flow."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.routers import build

PID = '00000000-0000-4000-8000-000000000001'


def request(method='POST', marker=True):
    async def receive():
        return {'type': 'http.request', 'body': b'{}', 'more_body': False}
    headers = [(b'host', b'flow.example'), (b'origin', b'https://flow.example'),
               (b'content-type', b'application/json'),
               (b'authorization', b'Bearer flow-jwt-fixture'), (b'x-sub-token', b'flow-sub-fixture'),
               (b'x-forwarded-for', b'203.0.113.1'), (b'x-api-key', b'private-key'),
               (b'cookie', b'platform_cookie=private; flow_store_session=store-session')]
    if marker:
        headers.append((b'x-flow-store-preview', b'1'))
    return Request({'type': 'http', 'method': method, 'path': f'/api/projects/{PID}/proxy/api/login',
                    'headers': headers, 'query_string': b'', 'server': ('flow.example', 443), 'scheme': 'https'}, receive)


@pytest.mark.asyncio
async def test_preview_strips_platform_credentials_and_scopes_store_cookies():
    captured = []
    def upstream(req):
        captured.append(req)
        return httpx.Response(200, json={'ok': True}, headers=[
            ('set-cookie', 'flow_store_session=next; HttpOnly; Path=/; SameSite=lax; Domain=example.com'),
            ('set-cookie', 'unrelated=value; Path=/')])
    session = SimpleNamespace(preview_url='https://preview-example.vercel.run/_flow_preview/per-run-capability', store_dirty=False)
    @asynccontextmanager
    async def access(_pid):
        yield session
    real_client = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return real_client(transport=httpx.MockTransport(upstream), **kwargs)
    save = AsyncMock()
    with patch.object(build, '_require_project_owner', AsyncMock()), \
         patch.object(build.isolated, 'store_access', access), \
         patch.object(build.isolated, 'persist_store', save), \
         patch.object(build.httpx, 'AsyncClient', side_effect=client):
        response = await build.proxy_to_project(PID, 'api/login', request())
    headers = captured[0].headers
    for name in ('authorization', 'x-sub-token', 'x-api-key', 'x-forwarded-for'):
        assert name not in headers
    assert headers['cookie'] == '__Host-flow_preview=per-run-capability; flow_store_session=store-session'
    assert 'platform_cookie' not in headers['cookie']
    assert headers['x-flow-preview-origin'] == 'https://flow.example'
    assert captured[0].url.host == 'preview-example.vercel.run'
    save.assert_awaited_once_with(session)
    cookies = response.headers.getlist('set-cookie')
    assert len(cookies) == 1 and f'Path=/api/projects/{PID}/proxy/' in cookies[0]
    assert 'HttpOnly' in cookies[0] and 'Secure' in cookies[0] and 'Domain=' not in cookies[0]
    assert response.headers['content-type'] == 'application/octet-stream'
    assert response.headers['content-disposition'].startswith('attachment')
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.asyncio
async def test_direct_same_origin_preview_navigation_is_rejected():
    with patch.object(build, '_require_project_owner', AsyncMock()):
        with pytest.raises(HTTPException) as error:
            await build.proxy_to_project(PID, '', request(method='GET', marker=False))
    assert error.value.status_code == 410


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['../../admin', 'http://other.example', '//other.example', 'api/%2fadmin', 'assets/evil.js'])
async def test_bridge_cannot_request_arbitrary_paths(path):
    with patch.object(build, '_require_project_owner', AsyncMock()):
        with pytest.raises(HTTPException) as error:
            await build.proxy_to_project(PID, path, request())
    assert error.value.status_code == 400
