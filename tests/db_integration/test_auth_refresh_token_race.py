"""Real-PostgreSQL regression test — the refresh-token rotation race
condition in app/routers/auth_users.py::refresh_token.

The endpoint used to SELECT the session row, then UPDATE it in a second
statement — a real TOCTOU window: two concurrent requests presenting the
same refresh_token could both read the still-valid row before either write
landed, so both would be accepted and each handed a *different* new
refresh_token, but the database can only hold one. Reproduced against real
PostgreSQL before the fix (see /tmp scratch repro during development); this
test pins the fixed behavior (a single atomic UPDATE ... WHERE ...
RETURNING compare-and-swap) so the race cannot silently come back.

Mocking asyncpg would prove nothing here — the whole bug is about how two
real concurrent connections interleave against a real table, which is
exactly what this test exercises.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def one_user_session(pg_pool):
    """One real user with one real, currently-valid session — created
    directly against the schema refresh_token actually reads/writes
    (users + user_sessions, from app.core.db.init_db), not a hand-rolled
    substitute."""
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    old_token = f"old-token-{uuid.uuid4().hex}"
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES ($1, $2, $3)",
            user_id, f"race-{uuid.uuid4().hex[:8]}@example.com", "irrelevant-hash",
        )
        await conn.execute(
            "INSERT INTO user_sessions (id, user_id, refresh_token, expires_at) "
            "VALUES ($1, $2, $3, NOW() + INTERVAL '1 day')",
            session_id, user_id, old_token,
        )
    return {"user_id": str(user_id), "session_id": str(session_id), "old_token": old_token}


class TestRefreshTokenRotationIsAtomic:
    async def test_two_concurrent_refreshes_of_the_same_token_only_one_succeeds(
        self, pg_pool, one_user_session,
    ):
        from app.routers.auth_users import refresh_token, RefreshRequest
        from fastapi import HTTPException

        old_token = one_user_session["old_token"]
        body = RefreshRequest(refresh_token=old_token)

        results = await asyncio.gather(
            refresh_token(body, _rl=None),
            refresh_token(body, _rl=None),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        # Exactly one of the two concurrent requests for the same
        # refresh_token succeeds -- not zero (the fix must not be
        # over-strict and reject a legitimate lone refresh), and not two
        # (that would be the race itself, still open).
        assert len(successes) == 1, (
            f"expected exactly 1 success, got {len(successes)} — "
            f"results={results}"
        )
        assert len(failures) == 1
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 401

        # The one new refresh_token actually returned to the caller must be
        # the one the database actually holds -- proves there's no second,
        # silently-invalid token handed to a "losing" caller anymore.
        winner_new_token = successes[0]["refresh_token"]
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT refresh_token FROM user_sessions WHERE id=$1",
                uuid.UUID(one_user_session["session_id"]),
            )
        assert row["refresh_token"] == winner_new_token
        assert row["refresh_token"] != old_token

    async def test_replaying_an_already_rotated_token_is_cleanly_rejected(
        self, pg_pool, one_user_session,
    ):
        """Sequential (not concurrent) reuse-detection case: once a token
        has been rotated away by a legitimate refresh, presenting the OLD
        value again (e.g. a stolen/leaked token used after the real client
        already rotated) must fail -- it must not be treated as still
        valid just because the row still exists under a new token value."""
        from app.routers.auth_users import refresh_token, RefreshRequest
        from fastapi import HTTPException

        old_token = one_user_session["old_token"]
        first = await refresh_token(RefreshRequest(refresh_token=old_token), _rl=None)
        assert first["refresh_token"] != old_token

        with pytest.raises(HTTPException) as exc:
            await refresh_token(RefreshRequest(refresh_token=old_token), _rl=None)
        assert exc.value.status_code == 401

    async def test_expired_session_still_rejected_and_cleaned_up(self, pg_pool):
        from app.routers.auth_users import refresh_token, RefreshRequest
        from fastapi import HTTPException

        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        expired_token = f"expired-token-{uuid.uuid4().hex}"
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, email, password_hash) VALUES ($1, $2, $3)",
                user_id, f"expired-{uuid.uuid4().hex[:8]}@example.com", "irrelevant-hash",
            )
            await conn.execute(
                "INSERT INTO user_sessions (id, user_id, refresh_token, expires_at) "
                "VALUES ($1, $2, $3, $4)",
                session_id, user_id, expired_token,
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1),
            )

        with pytest.raises(HTTPException) as exc:
            await refresh_token(RefreshRequest(refresh_token=expired_token), _rl=None)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

        async with pg_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_sessions WHERE id=$1", session_id,
            )
        assert count == 0  # the expired row is cleaned up, not left behind

    async def test_successful_refresh_returns_a_working_access_token(
        self, pg_pool, one_user_session,
    ):
        from app.routers.auth_users import refresh_token, RefreshRequest
        from app.core.jwt_utils import decode_access_token

        result = await refresh_token(
            RefreshRequest(refresh_token=one_user_session["old_token"]), _rl=None,
        )
        payload = decode_access_token(result["access_token"])
        assert payload["sub"] == one_user_session["user_id"]
        assert result["token_type"] == "bearer"
