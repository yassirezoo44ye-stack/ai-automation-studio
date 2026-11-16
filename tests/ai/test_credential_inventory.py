import uuid
import pytest
from app.ai.credential_inventory import read_rotation_inventory, read_rotation_coverage

class FakeConn:
    async def fetch(self, sql):
        assert "encrypted_key" not in sql
        return [{"org_id": uuid.UUID(int=1), "user_id": uuid.UUID(int=2), "credential_count": 3}]
    async def fetchrow(self, sql):
        assert "LEFT JOIN" in sql
        return {"expected": 4, "enrolled": 3, "verified": 2}

@pytest.mark.asyncio
async def test_inventory_excludes_secrets():
    result = await read_rotation_inventory(FakeConn())
    assert result == [{"org_id": str(uuid.UUID(int=1)), "user_id": str(uuid.UUID(int=2)), "credential_count": 3}]

@pytest.mark.asyncio
async def test_coverage_distinguishes_missing_scopes():
    assert await read_rotation_coverage(FakeConn()) == {"expected": 4, "enrolled": 3, "verified": 2}

@pytest.mark.asyncio
async def test_coverage_rejects_stale_verified_checkpoint_in_query():
    class QueryConn:
        async def fetchrow(self, sql):
            assert "k.updated_at > c.updated_at" in sql
            assert "NOT EXISTS" in sql
            return {"expected": 1, "enrolled": 1, "verified": 0}
    assert (await read_rotation_coverage(QueryConn()))["verified"] == 0
