from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from starlette.requests import Request
from app.routers import build


@pytest.mark.asyncio
async def test_preview_strips_platform_credentials_and_scopes_store_cookies():
    async def receive():
        return {'type':'http.request','body':b'{}','more_body':False}
    request=Request({'type':'http','method':'POST','path':'/api/projects/p1/proxy/api/login','headers':[(b'host',b'flow.example'),(b'origin',b'https://flow.example'),(b'authorization',b'Bearer flow-jwt-fixture'),(b'x-sub-token',b'flow-sub-fixture'),(b'x-flow-store-preview',b'1'),(b'x-forwarded-for',b'203.0.113.1'),(b'cookie',b'platform_cookie=private; flow_store_session=store-session')],'query_string':b'','server':('flow.example',443),'scheme':'https'},receive)
    upstream=httpx.Response(200,json={'ok':True},headers=[('set-cookie','flow_store_session=next; HttpOnly; Path=/; SameSite=lax'),('set-cookie','other=value; Path=/')])
    transport=MagicMock()
    transport.request=AsyncMock(return_value=upstream)
    context=MagicMock()
    context.__aenter__=AsyncMock(return_value=transport)
    context.__aexit__=AsyncMock(return_value=False)
    with patch.object(build,'_require_project_owner',AsyncMock()),patch.object(build.process_mgr,'get_running',return_value=SimpleNamespace(port=8100)),patch.object(build.httpx,'AsyncClient',return_value=context):
        response=await build.proxy_to_project('p1','api/login',request)
    headers=transport.request.call_args.kwargs['headers']
    assert 'authorization' not in headers and 'x-sub-token' not in headers
    assert 'x-forwarded-for' not in headers
    assert headers['cookie']=='flow_store_session=store-session'
    assert headers['x-flow-preview-origin']=='https://flow.example'
    cookies=response.headers.getlist('set-cookie')
    assert len(cookies)==2 and all('Path=/api/projects/p1/proxy/' in cookie for cookie in cookies)
    assert 'HttpOnly' in cookies[0]
