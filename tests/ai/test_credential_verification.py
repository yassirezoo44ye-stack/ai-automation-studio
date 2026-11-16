"""Primary-only verification must never leak credential values."""
import uuid
import pytest
from cryptography.fernet import Fernet
from app.ai.credential_verification import verify_user_primary_key

class FakeConn:
    def __init__(self, rows):
        self.rows = rows
    async def fetch(self, sql, *args):
        assert "org_id=$1" in sql and "user_id=$2" in sql
        return self.rows

@pytest.mark.asyncio
async def test_detects_old_ciphertext_without_exposing_secrets(monkeypatch):
    old, new = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setenv("BYOK_FERNET_KEY", new.decode())
    monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode())
    conn = FakeConn([
        {"encrypted_key": Fernet(old).encrypt(b"old-secret").decode()},
        {"encrypted_key": Fernet(new).encrypt(b"new-secret").decode()},
    ])
    result = await verify_user_primary_key(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
    assert result == {"scanned": 2, "not_primary": 1, "complete": False}
    assert "secret" not in repr(result)

@pytest.mark.asyncio
async def test_primary_only_complete(monkeypatch):
    new = Fernet.generate_key()
    monkeypatch.setenv("BYOK_FERNET_KEY", new.decode())
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    conn = FakeConn([{"encrypted_key": Fernet(new).encrypt(b"secret").decode()}])
    assert (await verify_user_primary_key(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4())))["complete"]

@pytest.mark.asyncio
async def test_invalid_key_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("BYOK_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        await verify_user_primary_key(FakeConn([]), org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
