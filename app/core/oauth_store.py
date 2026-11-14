"""Optional durable, single-use OAuth slots backed by the existing database."""
import hashlib
import json
import os

from cryptography.fernet import Fernet

from app.core.auth import derive_fernet_key
from app.core.db import get_pool

DDL = """
CREATE TABLE IF NOT EXISTS oauth_transient_slots (
    key_hash TEXT PRIMARY KEY,
    value_hash TEXT NOT NULL,
    payload_encrypted TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_transient_expiry ON oauth_transient_slots(expires_at);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PostgresOAuthStore:
    async def _put(self, key: str, value: str, ttl: int) -> None:
        encrypted = Fernet(derive_fernet_key("oauth-transient")).encrypt(value.encode()).decode()
        async with get_pool().acquire() as conn:
            await conn.execute("DELETE FROM oauth_transient_slots WHERE expires_at <= now()")
            await conn.execute(
                "INSERT INTO oauth_transient_slots(key_hash,value_hash,payload_encrypted,expires_at) "
                "VALUES ($1,$2,$3,now()+$4*interval '1 second')",
                _hash(key), _hash(value), encrypted, ttl,
            )

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._put(key, value, ttl)

    async def set_json(self, key: str, value: dict, ttl: int) -> None:
        await self._put(key, json.dumps(value), ttl)

    async def get_and_delete_if_matches(self, key: str, expected: str) -> bool | None:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM oauth_transient_slots WHERE key_hash=$1 AND value_hash=$2 "
                "AND expires_at>now() RETURNING key_hash", _hash(key), _hash(expected),
            )
            if row:
                return True
            exists = await conn.fetchval(
                "SELECT 1 FROM oauth_transient_slots WHERE key_hash=$1 AND expires_at>now()", _hash(key),
            )
            return False if exists else None

    async def get_json_and_delete(self, key: str) -> dict | None:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM oauth_transient_slots WHERE key_hash=$1 AND expires_at>now() "
                "RETURNING payload_encrypted", _hash(key),
            )
        if row is None:
            return None
        raw = Fernet(derive_fernet_key("oauth-transient")).decrypt(row["payload_encrypted"].encode())
        return json.loads(raw)


async def get_oauth_store():
    storage = os.getenv("OAUTH_STORAGE", "cache")
    if storage == "postgres":
        return PostgresOAuthStore()
    if storage != "cache":
        raise RuntimeError("Unsupported OAuth storage backend")
    from app.core.cache.redis_adapter import get_redis
    return await get_redis()
