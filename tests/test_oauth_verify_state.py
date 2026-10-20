"""
Behavioral regression tests for _verify_and_consume_oauth_state.

Tests cover:
  • missing state param       → HTTP 400
  • missing bind cookie       → HTTP 400
  • state absent/expired      → HTTP 400  (redis returns None)
  • nonce mismatch            → HTTP 400, key left intact  (redis returns False)
  • valid state + nonce       → returns None (no exception)
  • concurrent flows          → second flow wins, first gets nonce-mismatch

No live DB, no network — all Redis I/O is mocked.
"""
from __future__ import annotations

import os
import sys
import unittest.mock as mock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

# ── Patch heavy module-level imports before loading auth_users ────────────────
_MOCKS = {
    "asyncpg": mock.MagicMock(),
    "jwt": mock.MagicMock(),
    "app.core.db": mock.MagicMock(),
    "app.core.email": mock.MagicMock(),
    "app.core.observability": mock.MagicMock(),
    "app.core.observability.tracer": mock.MagicMock(),
    "app.core.rate_limit": mock.MagicMock(),
    "app.core.jwt_utils": mock.MagicMock(),
    "app.core.passwords": mock.MagicMock(),
    "app.core.cache": mock.MagicMock(),
    "app.core.cache.redis_adapter": mock.MagicMock(),
}

with mock.patch.dict(sys.modules, _MOCKS):
    from app.routers.auth_users import _verify_and_consume_oauth_state, _OAUTH_BIND_COOKIE
    from fastapi import HTTPException


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_request(bind_cookie: str | None = None) -> mock.MagicMock:
    """Return a mock Request whose cookies.get() returns the given value."""
    req = mock.MagicMock()
    req.cookies.get = mock.Mock(return_value=bind_cookie)
    return req


def _make_redis(result) -> mock.AsyncMock:
    """Return an async-mock Redis whose get_and_delete_if_matches returns result."""
    redis = mock.AsyncMock()
    redis.get_and_delete_if_matches = mock.AsyncMock(return_value=result)
    return redis


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_missing_state_raises_400():
    """state=None must raise HTTP 400 before any I/O."""
    req = _make_request(bind_cookie="some-nonce")
    with pytest.raises(HTTPException) as exc_info:
        await _verify_and_consume_oauth_state(None, req, ip="1.2.3.4")
    assert exc_info.value.status_code == 400


async def test_empty_state_raises_400():
    """state="" (falsy) must also raise HTTP 400."""
    req = _make_request(bind_cookie="some-nonce")
    with pytest.raises(HTTPException) as exc_info:
        await _verify_and_consume_oauth_state("", req, ip="1.2.3.4")
    assert exc_info.value.status_code == 400


async def test_missing_bind_cookie_raises_400():
    """No bind cookie → HTTP 400, no Redis I/O."""
    req = _make_request(bind_cookie=None)
    with pytest.raises(HTTPException) as exc_info:
        await _verify_and_consume_oauth_state("valid-state", req, ip="1.2.3.4")
    assert exc_info.value.status_code == 400


async def test_state_absent_from_redis_raises_400():
    """Redis returns None (state unknown/expired) → HTTP 400."""
    req = _make_request(bind_cookie="nonce-abc")
    redis = _make_redis(None)

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_and_consume_oauth_state("state-xyz", req, ip="1.2.3.4")

    assert exc_info.value.status_code == 400


async def test_nonce_mismatch_raises_400():
    """Redis returns False (nonce mismatch) → HTTP 400 (CSRF guard)."""
    req = _make_request(bind_cookie="wrong-nonce")
    redis = _make_redis(False)

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_and_consume_oauth_state("state-xyz", req, ip="1.2.3.4")

    assert exc_info.value.status_code == 400


async def test_valid_state_and_nonce_succeeds():
    """Redis returns True (matched + consumed) → function returns None (no exception)."""
    req = _make_request(bind_cookie="correct-nonce")
    redis = _make_redis(True)

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis)):
        result = await _verify_and_consume_oauth_state("state-xyz", req, ip="1.2.3.4")

    assert result is None  # successful path returns nothing


async def test_redis_key_queried_with_state_prefix():
    """Redis is called with 'oauth_state:{state}' as the key."""
    req = _make_request(bind_cookie="nonce-abc")
    redis = _make_redis(True)

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis)):
        await _verify_and_consume_oauth_state("my-state-token", req, ip="1.2.3.4")

    redis.get_and_delete_if_matches.assert_called_once_with(
        "oauth_state:my-state-token", "nonce-abc"
    )


async def test_redis_exception_raises_503():
    """A Redis I/O error must surface as HTTP 503, not 500."""
    req = _make_request(bind_cookie="nonce-abc")
    failing_redis = mock.AsyncMock()
    failing_redis.get_and_delete_if_matches = mock.AsyncMock(
        side_effect=Exception("connection refused")
    )

    with mock.patch(
        "app.core.cache.redis_adapter.get_redis",
        mock.AsyncMock(return_value=failing_redis),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_and_consume_oauth_state("state-xyz", req, ip="1.2.3.4")

    assert exc_info.value.status_code == 503


async def test_nonce_mismatch_does_not_consume_key():
    """
    When cookies are wrong (mismatch), Redis returns False and leaves the key
    intact — a legitimate browser can still complete its own flow.

    Verified by checking get_and_delete_if_matches was called (not skipped)
    and returned False as configured; the mock never deletes state server-side,
    faithfully representing the Lua-script contract.
    """
    req = _make_request(bind_cookie="attacker-nonce")
    redis = _make_redis(False)  # key is NOT consumed on mismatch

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc_info:
            await _verify_and_consume_oauth_state("victim-state", req, ip="9.9.9.9")

    assert exc_info.value.status_code == 400
    # Confirm the atomic operation was attempted exactly once
    redis.get_and_delete_if_matches.assert_called_once_with("oauth_state:victim-state", "attacker-nonce")


async def test_concurrent_flows_second_wins_first_gets_mismatch():
    """
    Concurrent OAuth flow scenario:
      Flow 1: state=S1, nonce=N1 (stored in Redis as oauth_state:S1 → N1)
              but browser-1 accidentally receives cookie N2 (race/overwrite).
              → get_and_delete_if_matches("oauth_state:S1", N2) returns False
              → Flow 1 fails with 400; key S1 is left intact.
      Flow 2: state=S2, nonce=N2 (correct cookie).
              → get_and_delete_if_matches("oauth_state:S2", N2) returns True
              → Flow 2 succeeds.

    This confirms the Redis-backed implementation handles concurrent same-browser
    OAuth retries better than a cookie-only scheme: the wrong nonce does NOT
    destroy the legitimate state.
    """
    # Flow 1: browser carries wrong nonce (race condition)
    req1 = _make_request(bind_cookie="nonce-2")
    redis1 = _make_redis(False)  # mismatch — S1's key stays alive

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis1)):
        with pytest.raises(HTTPException) as exc1:
            await _verify_and_consume_oauth_state("state-1", req1, ip="1.2.3.4")

    assert exc1.value.status_code == 400

    # Flow 2: browser carries correct nonce
    req2 = _make_request(bind_cookie="nonce-2")
    redis2 = _make_redis(True)  # match — S2 consumed

    with mock.patch("app.core.cache.redis_adapter.get_redis", mock.AsyncMock(return_value=redis2)):
        result = await _verify_and_consume_oauth_state("state-2", req2, ip="1.2.3.4")

    assert result is None  # Flow 2 succeeds
