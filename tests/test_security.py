"""
Unit tests for app.core.security rate-limiter.
No database or network required.
"""
import time as _t
import uuid

import pytest

from app.core.security import check_rate_limit, _rl_store


def fresh() -> str:
    return f"test:{uuid.uuid4()}"


class TestCheckRateLimit:
    def test_allows_under_limit(self):
        key = fresh()
        for _ in range(9):
            assert check_rate_limit(key, max_calls=10, window=60) is True

    def test_blocks_at_limit(self):
        key = fresh()
        for _ in range(10):
            check_rate_limit(key, max_calls=10, window=60)
        assert check_rate_limit(key, max_calls=10, window=60) is False

    def test_independent_keys(self):
        k1, k2 = fresh(), fresh()
        for _ in range(10):
            check_rate_limit(k1, max_calls=10, window=60)
        assert check_rate_limit(k2, max_calls=10, window=60) is True

    def test_expired_entries_reset(self):
        key = fresh()
        _rl_store[key] = [_t.time() - 120] * 10  # stale entries
        assert check_rate_limit(key, max_calls=10, window=60) is True

    def test_window_1_allows_once(self):
        key = fresh()
        assert check_rate_limit(key, max_calls=1, window=60) is True
        assert check_rate_limit(key, max_calls=1, window=60) is False
