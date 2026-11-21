"""Security regression: JWT revocation must be honored across worker processes.

The shared decoder must reject a revoked token even after clearing process-local state.
"""
import pytest
import jwt

from app.core import jwt_utils


@pytest.mark.asyncio
async def test_revoked_token_is_rejected_in_another_worker(monkeypatch):
    from unittest.mock import AsyncMock, patch

    token = jwt_utils.make_access_token("security-worker-user", "worker@example.com")
    shared = {}

    class SharedCache:
        backend = "redis"

        async def set(self, key, value, ttl=None):
            shared[key] = value

        async def get(self, key):
            return shared.get(key)

    cache = SharedCache()
    monkeypatch.setattr(jwt_utils, "_revoked_before", {})
    with patch("app.core.cache.get_redis", new=AsyncMock(return_value=cache)):
        await jwt_utils.revoke_user_tokens("security-worker-user")
        # A second worker has no process-local revocation state.
        monkeypatch.setattr(jwt_utils, "_revoked_before", {})
        with pytest.raises(jwt.PyJWTError):
            await jwt_utils.decode_access_token_shared(token)

@pytest.mark.asyncio
async def test_shared_revocation_fails_closed_without_redis(monkeypatch):
    from unittest.mock import AsyncMock, patch

    class LocalCache:
        backend = "local"

    monkeypatch.setattr(jwt_utils, "_revoked_before", {})
    token = jwt_utils.make_access_token("redis-down-user", "down@example.com")
    with patch("app.core.cache.get_redis", new=AsyncMock(return_value=LocalCache())):
        with pytest.raises(jwt.PyJWTError):
            await jwt_utils.decode_access_token_shared(token)
        with pytest.raises(RuntimeError, match="requires shared Redis"):
            await jwt_utils.revoke_user_tokens("redis-down-user")


@pytest.mark.asyncio
async def test_shared_revocation_recovers_after_redis_returns(monkeypatch):
    from unittest.mock import AsyncMock, patch

    token = jwt_utils.make_access_token("redis-recovery-user", "recovery@example.com")
    shared = {}

    class RedisCache:
        backend = "redis"

        async def get(self, key):
            return shared.get(key)

        async def set(self, key, value, ttl=None):
            shared[key] = value

    class LocalCache:
        backend = "local"

    monkeypatch.setattr(jwt_utils, "_revoked_before", {})
    cache = RedisCache()
    get_cache = AsyncMock(side_effect=[LocalCache(), cache, cache, cache])
    with patch("app.core.cache.get_redis", new=get_cache):
        with pytest.raises(jwt.PyJWTError):
            await jwt_utils.decode_access_token_shared(token)
        assert (await jwt_utils.decode_access_token_shared(token))["sub"] == "redis-recovery-user"
        await jwt_utils.revoke_user_tokens("redis-recovery-user")
        monkeypatch.setattr(jwt_utils, "_revoked_before", {})
        with pytest.raises(jwt.PyJWTError):
            await jwt_utils.decode_access_token_shared(token)
