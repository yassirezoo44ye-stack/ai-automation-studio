import uuid
import pytest
from app.ai.credential_lease import claim_checkpoint, finish_checkpoint

class FakeConn:
    def __init__(self, row=None):
        self.row = row
        self.calls = []
    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.row

@pytest.mark.asyncio
async def test_claim_returns_token_and_uses_atomic_update():
    conn = FakeConn({"lease_token": uuid.uuid4()})
    token = await claim_checkpoint(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
    assert token == str(conn.row["lease_token"])
    assert "UPDATE ai_credential_rotation_checkpoints" in conn.calls[0][0]
    assert "lease_expires_at < now()" in conn.calls[0][0]

@pytest.mark.asyncio
async def test_claim_not_available():
    conn = FakeConn()
    assert await claim_checkpoint(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())) is None

@pytest.mark.asyncio
async def test_finish_requires_current_lease():
    conn = FakeConn({"status": "verified"})
    assert await finish_checkpoint(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()), verified=True)
    assert "lease_token=$3" in conn.calls[0][0]
    assert "lease_expires_at > now()" in conn.calls[0][0]

@pytest.mark.asyncio
async def test_finish_rejects_secret_error_messages():
    with pytest.raises(ValueError):
        await finish_checkpoint(FakeConn(), org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), lease_token=str(uuid.uuid4()), verified=False, error_code="api_key=secret")

@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [0, 29, 3601, True])
async def test_invalid_lease_length(seconds):
    with pytest.raises(ValueError):
        await claim_checkpoint(FakeConn(), org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), lease_seconds=seconds)
