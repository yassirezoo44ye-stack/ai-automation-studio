import pytest
from cryptography.fernet import Fernet
from app.ai.credential_final_audit import verify_all_primary_ciphertexts

class FakeTransaction:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): self.conn.active = True
    async def __aexit__(self, exc_type, exc, tb): self.conn.active = False

class FakeConn:
    def __init__(self, rows): self.rows = rows; self.active = False
    def transaction(self, *, isolation, readonly):
        assert isolation == "repeatable_read" and readonly is True
        return FakeTransaction(self)
    async def fetch(self, sql):
        assert self.active
        assert "encrypted_key" in sql
        return [{"encrypted_key": item} for item in self.rows]

@pytest.mark.asyncio
async def test_final_audit_primary_only_and_corruption(monkeypatch):
    primary, old = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setenv("BYOK_FERNET_KEY", primary.decode())
    monkeypatch.setenv("BYOK_FERNET_PREVIOUS_KEYS", old.decode())
    good = Fernet(primary).encrypt(b"secret").decode()
    legacy = Fernet(old).encrypt(b"secret").decode()
    assert await verify_all_primary_ciphertexts(FakeConn([good])) == {
        "scanned": 1, "not_primary": 0, "complete": True}
    assert await verify_all_primary_ciphertexts(FakeConn([good, legacy, "corrupt"])) == {
        "scanned": 3, "not_primary": 2, "complete": False}

@pytest.mark.asyncio
async def test_final_audit_empty_inventory_fails_closed(monkeypatch):
    monkeypatch.setenv("BYOK_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("BYOK_FERNET_PREVIOUS_KEYS", raising=False)
    assert (await verify_all_primary_ciphertexts(FakeConn([])))["complete"] is False
