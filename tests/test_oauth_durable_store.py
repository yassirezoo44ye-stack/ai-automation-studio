from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from app.core import oauth_store as store
from app.core.auth import derive_fernet_key


@pytest.fixture
def conn(monkeypatch):
    db = AsyncMock()
    @asynccontextmanager
    async def acquire():
        yield db
    class Pool:
        pass
    pool = Pool()
    pool.acquire = acquire
    monkeypatch.setattr(store, "get_pool", lambda: pool)
    return db


@pytest.mark.asyncio
async def test_state_and_payload_are_not_stored_in_plaintext(conn):
    await store.PostgresOAuthStore().set("state-secret", "nonce-secret", ttl=600)
    sql, key, value_hash, payload, ttl = conn.execute.call_args.args
    assert key == store._hash("state-secret")
    assert value_hash == store._hash("nonce-secret")
    assert "nonce-secret" not in payload
    assert Fernet(derive_fernet_key("oauth-transient")).decrypt(payload.encode()) == b"nonce-secret"
    assert ttl == 600


@pytest.mark.asyncio
async def test_nonce_mismatch_preserves_slot(conn):
    conn.fetchrow.return_value = None
    conn.fetchval.return_value = 1
    assert await store.PostgresOAuthStore().get_and_delete_if_matches("key", "wrong") is False
    assert "value_hash=$2" in conn.fetchrow.call_args.args[0]
    assert "expires_at>now()" in conn.fetchrow.call_args.args[0]


@pytest.mark.asyncio
async def test_exchange_single_use_and_survives_store_recreation(conn):
    first = store.PostgresOAuthStore()
    await first.set_json("exchange-key", {"access_token": "test-only"}, ttl=60)
    encrypted = conn.execute.call_args.args[3]
    conn.fetchrow.side_effect = [{"payload_encrypted": encrypted}, None]
    second = store.PostgresOAuthStore()
    assert await second.get_json_and_delete("exchange-key") == {"access_token": "test-only"}
    assert await second.get_json_and_delete("exchange-key") is None
    assert "DELETE FROM" in conn.fetchrow.call_args.args[0]


@pytest.mark.asyncio
async def test_unknown_storage_fails_closed(monkeypatch):
    monkeypatch.setenv("OAUTH_STORAGE", "unknown")
    with pytest.raises(RuntimeError):
        await store.get_oauth_store()
