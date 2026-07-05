"""
Unit tests for app.core.rate_limit.
Runs without a live database or HTTP server.
"""
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.rate_limit import check_rate_limit, require_rate_limit, rl_store


@pytest.fixture(autouse=True)
def clear_store():
    rl_store.clear()
    yield
    rl_store.clear()


def _req(ip: str = "1.2.3.4", owner: str = "test@example.com") -> MagicMock:
    req = MagicMock()
    req.headers.get = lambda k, d="": ip if "Forwarded" in k else d
    req.client.host = ip
    req.state.owner = owner
    req.state.user_id = owner
    return req


class TestCheckRateLimit:
    def test_allows_up_to_max(self):
        for _ in range(5):
            assert check_rate_limit("test:key", max_calls=5, window=60) is True

    def test_blocks_on_overflow(self):
        for _ in range(5):
            check_rate_limit("test:key", max_calls=5, window=60)
        assert check_rate_limit("test:key", max_calls=5, window=60) is False

    def test_window_expires(self):
        check_rate_limit("test:key", max_calls=1, window=1)
        assert check_rate_limit("test:key", max_calls=1, window=1) is False
        time.sleep(1.05)
        assert check_rate_limit("test:key", max_calls=1, window=1) is True

    def test_independent_keys(self):
        for _ in range(5):
            check_rate_limit("key:a", max_calls=5, window=60)
        assert check_rate_limit("key:a", max_calls=5, window=60) is False
        assert check_rate_limit("key:b", max_calls=5, window=60) is True


class TestRequireRateLimit:
    def test_passes_within_limit(self):
        req = _req()
        for _ in range(3):
            require_rate_limit(req, key_prefix="test", max_calls=3, window=60)

    def test_raises_429_on_overflow(self):
        req = _req()
        for _ in range(3):
            require_rate_limit(req, key_prefix="test", max_calls=3, window=60)
        with pytest.raises(HTTPException) as exc_info:
            require_rate_limit(req, key_prefix="test", max_calls=3, window=60)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_custom_error_detail(self):
        req = _req()
        for _ in range(1):
            require_rate_limit(req, key_prefix="t", max_calls=1, window=60)
        with pytest.raises(HTTPException) as exc_info:
            require_rate_limit(req, key_prefix="t", max_calls=1, window=60,
                               error_detail="Custom message")
        assert "Custom message" in exc_info.value.detail

    def test_different_ips_are_independent(self):
        for _ in range(2):
            require_rate_limit(_req("1.1.1.1"), key_prefix="t", max_calls=2, window=60)
        with pytest.raises(HTTPException):
            require_rate_limit(_req("1.1.1.1"), key_prefix="t", max_calls=2, window=60)
        require_rate_limit(_req("2.2.2.2"), key_prefix="t", max_calls=2, window=60)
