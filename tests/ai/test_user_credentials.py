"""Vault tests use fake DB; no live keys or production storage."""
import uuid

import pytest

from app.ai import user_credentials as vault

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())


class FakeConn:
    def __init__(self):
        self.row = None
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        if query.lstrip().startswith("INSERT"):
            self.row = {"encrypted_key": args[3]}
            return "INSERT 0 1"
        if query.lstrip().startswith("DELETE"):
            old = self.row
            self.row = None
            return "DELETE 1" if old else "DELETE 0"
        raise AssertionError("Unexpected SQL")

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.row


@pytest.fixture(autouse=True)
def test_key(monkeypatch):
    from cryptography.fernet import Fernet
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(vault, "_cipher", lambda: cipher)


@pytest.mark.asyncio
async def test_encrypted_roundtrip():
    conn = FakeConn()
    await vault.put_key(conn, org_id=ORG, user_id=USER, provider="openai", api_key="test-secret")
    assert "test-secret" not in conn.row["encrypted_key"]
    assert await vault.get_key_for_execution(conn, org_id=ORG, user_id=USER, provider="openai") == "test-secret"


@pytest.mark.asyncio
async def test_scoped_sql_and_revoke():
    conn = FakeConn()
    await vault.put_key(conn, org_id=ORG, user_id=USER, provider="openai", api_key="example")
    assert await vault.revoke_key(conn, org_id=ORG, user_id=USER, provider="openai")
    assert await vault.get_key_for_execution(conn, org_id=ORG, user_id=USER, provider="openai") is None
    for sql, args in conn.calls:
        assert "org_id" in sql and "user_id" in sql and "provider" in sql
        assert uuid.UUID(ORG) in args and uuid.UUID(USER) in args


@pytest.mark.asyncio
async def test_rejects_unsupported_provider():
    with pytest.raises(ValueError):
        await vault.put_key(FakeConn(), org_id=ORG, user_id=USER, provider="local", api_key="x")


@pytest.mark.asyncio
async def test_rejects_blank_secret():
    with pytest.raises(ValueError):
        await vault.put_key(FakeConn(), org_id=ORG, user_id=USER, provider="openai", api_key=" ")
