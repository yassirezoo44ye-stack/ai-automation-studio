"""
Security Regression Suite — Rate Limiting & Abuse Protection.

app/core/security.py used to be an independent, in-memory-only rate
limiter that keyed ai_rate_limit() on the client-spoofable LEFTMOST
X-Forwarded-For entry — an attacker could get a fresh bucket on every
single request just by sending a different fake leftmost IP, completely
defeating the "cap one account's AI-cost abuse" guard on build.py,
chat.py, design.py, agents.py, social.py, and youtube.py. It's now a
compatibility shim re-exporting app.core.rate_limit's implementation,
which keys on the trusted RIGHTMOST entry (the one appended by the
nearest real proxy) and adds Redis backing across instances.

The core sliding-window algorithm itself (allow/block/independent-keys/
window-expiry) is functional-correctness coverage, not security-motivated
— it lives in tests/test_rate_limit.py, not duplicated here.

Relocated (unmodified) from tests/test_security.py as part of the
Security Testing phase's tests/security/ reorganization. No behavioral
change.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.rate_limit import rl_store
from app.core.security import ai_rate_limit, check_rate_limit


@pytest.fixture(autouse=True)
def clear_store():
    rl_store.clear()
    yield
    rl_store.clear()


def _req(xff: str) -> MagicMock:
    req = MagicMock()
    req.headers.get = lambda k, d="": xff if k == "X-Forwarded-For" else d
    req.client.host = "unknown"
    return req


class TestShimReExportsFixedImplementation:
    def test_check_rate_limit_is_the_rate_limit_module_function(self):
        from app.core import rate_limit
        assert check_rate_limit is rate_limit.check_rate_limit

    def test_ai_rate_limit_is_the_rate_limit_module_function(self):
        from app.core import rate_limit
        assert ai_rate_limit is rate_limit.ai_rate_limit

    def test_check_rate_limit_still_works_through_the_old_import_path(self):
        key = "test:shim-still-works"
        for _ in range(5):
            assert check_rate_limit(key, max_calls=5, window=60) is True
        assert check_rate_limit(key, max_calls=5, window=60) is False


class TestAiRateLimitIgnoresSpoofedLeftmostForwardedFor:
    """The regression this consolidation exists to fix: varying the
    client-controlled leftmost X-Forwarded-For entry must NOT let the same
    caller dodge the limit by minting a fresh bucket on every call."""

    def test_spoofed_leftmost_ip_does_not_bypass_the_limit(self):
        with patch("app.core.auth.owner_email", return_value="victim@example.com"):
            # Same trusted rightmost hop (the real proxy-appended IP) on
            # every call, but a different attacker-supplied leftmost IP
            # each time — under the old app.core.security implementation
            # this alone reset the rate-limit bucket on every request.
            for i in range(20):
                ai_rate_limit(_req(f"10.0.0.{i}, 203.0.113.9"), max_calls=20, window=60)
            with pytest.raises(HTTPException) as exc_info:
                ai_rate_limit(_req("10.0.0.99, 203.0.113.9"), max_calls=20, window=60)
        assert exc_info.value.status_code == 429

    def test_different_trusted_rightmost_ip_gets_its_own_bucket(self):
        with patch("app.core.auth.owner_email", return_value="victim@example.com"):
            for i in range(20):
                ai_rate_limit(_req(f"10.0.0.{i}, 203.0.113.9"), max_calls=20, window=60)
            # A genuinely different caller (different rightmost/proxy-
            # appended IP) must still be able to make requests.
            ai_rate_limit(_req("10.0.0.1, 198.51.100.4"), max_calls=20, window=60)


if __name__ == "__main__":
    pytest.main([__file__])
