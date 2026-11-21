"""Focused fake-DB tests for per-user BYOK re-encryption."""
import uuid

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.ai.credential_rotation import rotate_user_credentials


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
    async def fetch(self, sql, *args):
        assert "FOR UPDATE" in sql
        assert "org_id=$1" in sql and "user_id=$2" in sql
        return self.rows[:args[2]]
    async def execute(self, sql, *args):
        self.updates.append(args)
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_reencrypts_with_primary_and_retains_plaintext(monkeypatch):
    old, new = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setenv("BYOK_FERNET_KEY", new.decode())
    monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode())
    conn = FakeConn([{"provider": "openai", "encrypted_key": Fernet(old).encrypt(b"secret").decode()}])
    org, user = str(uuid.uuid4()), str(uuid.uuid4())
    assert await rotate_user_credentials(conn, org_id=org, user_id=user) == {"scanned": 1, "rotated": 1}
    ciphertext = conn.updates[0][3].encode()
    assert Fernet(new).decrypt(ciphertext) == b"secret"
    with pytest.raises(InvalidToken):
        Fernet(old).decrypt(ciphertext)


@pytest.mark.asyncio
async def test_invalid_batch_size_rejected_without_query(monkeypatch):
    conn = FakeConn([])
    with pytest.raises(ValueError):
        await rotate_user_credentials(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), batch_size=0)
    assert conn.updates == []


@pytest.mark.asyncio
async def test_missing_previous_key_fails_closed(monkeypatch):
    old = Fernet.generate_key()
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    conn = FakeConn([{"provider": "openai", "encrypted_key": Fernet(old).encrypt(b"secret").decode()}])
    with pytest.raises(InvalidToken):
        await rotate_user_credentials(conn, org_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()))
    assert not conn.updates
