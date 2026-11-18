"""Security regression: JWT revocation must be honored across worker processes.

Current decode_access_token() consults only process-local _revoked_before.
The expected failure is intentionally strict, so CI reports an XPASS once fixed.
"""
import pytest
import jwt

from app.core import jwt_utils


@pytest.mark.xfail(
    strict=True,
    reason="decode_access_token currently ignores shared revocation state from another worker",
)
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
