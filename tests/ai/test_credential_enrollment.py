import uuid
import pytest
from app.ai.credential_enrollment import enroll_credential_scope

class FakeConn:
    def __init__(self, row): self.row = row; self.query = None
    async def fetchrow(self, sql, *args):
        self.query = sql
        return self.row

@pytest.mark.asyncio
async def test_enrollment_requires_existing_credentials():
    conn = FakeConn({"org_id": uuid.uuid4()})
    assert await enroll_credential_scope(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
    assert "WHERE EXISTS" in conn.query
    assert "ON CONFLICT" in conn.query

@pytest.mark.asyncio
async def test_enrollment_is_idempotent():
    conn = FakeConn(None)
    assert not await enroll_credential_scope(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
