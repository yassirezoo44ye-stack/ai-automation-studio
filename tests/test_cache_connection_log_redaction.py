"""Cache initialization must not log credential-bearing URLs or exceptions."""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.core.cache import redis_adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_connection_logs_contain_only_safe_metadata(monkeypatch, caplog, failure):
    private = "redis://local-user:private-password-fixture@localhost:6379/0?token=private-query-fixture"
    monkeypatch.setenv("REDIS_URL", private)
    monkeypatch.setattr(redis_adapter, "_instance", None)
    client = AsyncMock()
    if failure:
        client.ping.side_effect = RuntimeError(private)
    with caplog.at_level(logging.INFO, logger=redis_adapter.__name__), patch("redis.asyncio.from_url", return_value=client):
        adapter = await redis_adapter.get_redis()
    assert adapter.backend == ("local" if failure else "redis")
    assert "private-password-fixture" not in caplog.text
    assert "private-query-fixture" not in caplog.text
    assert private not in caplog.text
    assert any("cache: Redis" in record.message for record in caplog.records)
