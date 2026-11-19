"""A duplicate must have a real source; failed services never create fake cards."""
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.routers import discover


@pytest.mark.asyncio
async def test_clone_failure_does_not_insert_placeholder():
    org=str(uuid.uuid4())
    original={'id':uuid.uuid4(),'organization_id':uuid.uuid4(),'created_by_user_id':uuid.uuid4(),'type':'APP','title':'Published app','visibility':'public','source_type':'APP','source_id':uuid.uuid4()}
    conn=AsyncMock()
    conn.fetchrow.return_value=original
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    service=type('Service',(),{'clone_app':AsyncMock(side_effect=RuntimeError('source unavailable'))})()
    with patch.object(discover,'get_pool',return_value=Pool()),patch.object(discover,'_require_auth'),patch.object(discover,'_verified_org_id',AsyncMock(return_value=org)),patch.object(discover,'_get_user_id',return_value=str(uuid.uuid4())),patch('app.services.app_builder.get_app_builder_service',return_value=service):
        with pytest.raises(HTTPException) as exc:
            await discover.clone_creation(Request({'type':'http','headers':[]}),str(original['id']))
    assert exc.value.status_code==409
    assert all('INSERT' not in call.args[0] for call in conn.fetchrow.call_args_list)
