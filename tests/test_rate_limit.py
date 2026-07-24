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


class TestRlStoreGarbageCollection:
    """rl_store is a module-level dict keyed by every distinct IP/user
    combination ever rate-limit-checked — factory.py's global middleware
    alone creates one entry per distinct visitor with no natural upper
    bound. check_rate_limit() only ever trims a KEY's own list; nothing
    previously removed the key itself once its list emptied out, so a
    long-running process leaked one dict entry per unique caller forever.
    _maybe_gc() sweeps those out periodically."""

    def test_gc_evicts_keys_whose_entire_window_has_expired(self):
        import app.core.rate_limit as rl

        rl.rl_store["stale:key"] = [time.time() - 120]  # 2 min old, window=60
        rl._last_gc = 0.0  # force the next check to actually sweep

        check_rate_limit("unrelated:key", max_calls=10, window=60)

        assert "stale:key" not in rl.rl_store

    def test_gc_keeps_keys_with_recent_activity(self):
        import app.core.rate_limit as rl

        check_rate_limit("active:key", max_calls=10, window=60)
        rl._last_gc = 0.0  # force the next check to actually sweep

        check_rate_limit("unrelated:key", max_calls=10, window=60)

        assert "active:key" in rl.rl_store

    def test_gc_does_not_run_more_often_than_the_interval(self):
        import app.core.rate_limit as rl

        rl.rl_store["stale:key"] = [time.time() - 120]
        rl._last_gc = time.time()  # just ran — next call must not sweep again

        check_rate_limit("unrelated:key", max_calls=10, window=60)

        assert "stale:key" in rl.rl_store  # not swept — interval hasn't elapsed

    def test_gc_does_not_evict_the_key_being_checked_right_now(self):
        import app.core.rate_limit as rl

        rl._last_gc = 0.0
        # The key under check has no prior timestamps yet (defaultdict),
        # so a naive sweep could treat it as "dead" before it's recorded —
        # it must still end up allowed and present afterward.
        assert check_rate_limit("brand:new:key", max_calls=5, window=60) is True
        assert "brand:new:key" in rl.rl_store


class TestRateLimitObservability:
    """A 429 is a 4xx — it never touched http_errors_total (5xx-only) or
    any other metric, so a sustained rejection pattern (e.g. a
    cost-exposure attack against ai_rate_limit) was completely invisible
    to dashboards/alerting. require_rate_limit/ai_rate_limit must now
    increment rate_limit_rejections_total on every 429."""

    def test_require_rate_limit_increments_metric_on_429(self):
        from app.core.observability.metrics import get_metrics

        counter = get_metrics().counter("rate_limit_rejections_total")
        before = counter.value

        req = _req("9.9.9.9")
        require_rate_limit(req, key_prefix="obs_test", max_calls=1, window=60)  # allowed
        with pytest.raises(HTTPException):
            require_rate_limit(req, key_prefix="obs_test", max_calls=1, window=60)  # rejected

        assert counter.value == before + 1

    def test_require_rate_limit_does_not_increment_metric_when_allowed(self):
        from app.core.observability.metrics import get_metrics

        counter = get_metrics().counter("rate_limit_rejections_total")
        before = counter.value

        require_rate_limit(_req("8.8.8.8"), key_prefix="obs_test2", max_calls=5, window=60)

        assert counter.value == before

    def test_ai_rate_limit_increments_metric_on_429(self):
        from unittest.mock import patch

        from app.core.observability.metrics import get_metrics
        from app.core.rate_limit import ai_rate_limit

        counter = get_metrics().counter("rate_limit_rejections_total")
        before = counter.value

        req = _req("7.7.7.7")
        with patch("app.core.auth.owner_email", return_value="test@example.com"):
            ai_rate_limit(req, max_calls=1, window=60)  # allowed
            with pytest.raises(HTTPException):
                ai_rate_limit(req, max_calls=1, window=60)  # rejected

        assert counter.value == before + 1
