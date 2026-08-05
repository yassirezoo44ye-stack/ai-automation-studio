"""
Smoke test for the generic idempotency layer (app/core/idempotency.py),
Phase 1 "Deduplication" of the agent-runtime resilience initiative.

Proves, against a real database, that:
  1. init_idempotency_schema() runs cleanly (idempotent — safe against both
     a fresh DB and one that already has the table).
  2. UNIQUE(scope, key) is actually enforced at the DB level, not just
     relied upon by the idempotent() context manager's own logic.
  3. The idempotent() context manager itself round-trips correctly against
     a real pool: first call runs the work and persists the result: second
     call with the same (scope, key) replays without re-running it.
  4. A call that raises is recorded as 'failed', and a subsequent call with
     the same (scope, key) is treated as a fresh retry — not a permanent
     stuck duplicate (this is the exact bug being fixed in
     app/integrations/webhooks.py alongside this module).
  5. A genuinely concurrent duplicate (fresh 'pending' row) raises
     IdempotencyInProgress rather than being allowed to run the guarded
     work a second time — and once that row is old enough
     (EXTRACT(EPOCH FROM now() - created_at) past the module's staleness
     threshold, simulated here via a real UPDATE against Postgres, not a
     mock), the same key is correctly treated as an abandoned/crashed
     attempt and a retry is allowed through.

Schema-only + idempotent()-only scope — this does not touch any of the
concrete call sites (JobQueue.submit, POST /api/agentos/run,
integration_webhook_events). Test rows are cleaned up on exit either way.

Requires DATABASE_URL to point at a reachable Postgres instance.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL must be set before running this check.", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    import asyncpg
    from app.core.idempotency import idempotent, init_idempotency_schema

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    scope = "smoke-test"
    key = f"smoke-{uuid.uuid4()}"
    try:
        async with pool.acquire() as conn:
            await init_idempotency_schema(conn)
        print("[1/6] schema init: OK")

        # 2. UNIQUE(scope, key) enforced at the DB level directly (bypassing
        #    the ON CONFLICT DO NOTHING the context manager relies on, to
        #    prove the constraint itself is real, not just idempotent()'s
        #    own good behavior).
        await pool.execute(
            "INSERT INTO idempotency_keys (scope, key) VALUES ($1, $2)", scope, key,
        )
        try:
            await pool.execute(
                "INSERT INTO idempotency_keys (scope, key) VALUES ($1, $2)", scope, key,
            )
        except asyncpg.UniqueViolationError:
            print("[2/6] UNIQUE(scope, key) correctly rejects a duplicate insert: OK")
        else:
            raise AssertionError(
                f"idempotency_keys accepted a duplicate ({scope!r}, {key!r}) row — "
                "the UNIQUE constraint is not actually enforcing."
            )
        await pool.execute("DELETE FROM idempotency_keys WHERE scope=$1 AND key=$2", scope, key)

        # 3. idempotent() round-trip: first call runs + persists, second
        #    call replays without re-running.
        key2 = f"smoke-{uuid.uuid4()}"
        ran = []
        async with idempotent(scope, key2, pool=pool) as guard:
            assert not guard.is_replay
            ran.append(1)
            guard.result = {"smoke": True}
        async with idempotent(scope, key2, pool=pool) as guard2:
            assert guard2.is_replay, "second call with the same key was not treated as a replay"
            assert guard2.cached_result == {"smoke": True}
        assert ran == [1], "work ran more than once despite the second call being a replay"
        print("[3/6] idempotent() replay round-trip: OK")

        # 4. A failed attempt must not become a permanent stuck duplicate.
        key3 = f"smoke-{uuid.uuid4()}"
        try:
            async with idempotent(scope, key3, pool=pool) as guard:
                assert not guard.is_replay
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError to propagate out of the with-block")

        retried = []
        async with idempotent(scope, key3, pool=pool) as guard:
            assert not guard.is_replay, (
                "a call after a FAILED prior attempt was incorrectly treated as a "
                "duplicate/replay instead of a legitimate retry"
            )
            retried.append(1)
            guard.result = {"recovered": True}
        assert retried == [1]
        print("[4/6] failed-then-retried key is treated as a fresh retry, not a stuck duplicate: OK")

        # 5. A genuinely concurrent duplicate (fresh 'pending' row) must be
        #    rejected with IdempotencyInProgress, not silently re-run.
        from app.core.idempotency import IdempotencyInProgress

        key4 = f"smoke-{uuid.uuid4()}"
        cm = idempotent(scope, key4, pool=pool)
        guard = await cm.__aenter__()
        assert not guard.is_replay
        try:
            async with idempotent(scope, key4, pool=pool):
                raise AssertionError(
                    "a fresh 'pending' row (genuine concurrent duplicate) was "
                    "NOT rejected — IdempotencyInProgress should have been raised"
                )
        except IdempotencyInProgress:
            pass
        guard.result = {"first_caller_finished": True}
        await cm.__aexit__(None, None, None)
        print("[5/6] genuinely concurrent duplicate raises IdempotencyInProgress: OK")

        # Now simulate the first caller having crashed instead of finishing:
        # a 'pending' row old enough must be treated as abandoned and let a
        # retry through, proven here against real Postgres (not a mock's
        # controllable age_s) by directly backdating created_at.
        key5 = f"smoke-{uuid.uuid4()}"
        cm2 = idempotent(scope, key5, pool=pool)
        await cm2.__aenter__()  # never exited — simulates a dead process
        await pool.execute(
            "UPDATE idempotency_keys SET created_at = now() - interval '10 minutes' "
            "WHERE scope=$1 AND key=$2",
            scope, key5,
        )
        recovered = []
        async with idempotent(scope, key5, pool=pool) as guard2:
            assert not guard2.is_replay, (
                "a stale 'pending' row (older than the staleness threshold) was "
                "incorrectly treated as still in-flight"
            )
            recovered.append(1)
            guard2.result = {"recovered": True}
        assert recovered == [1]
        print("[6/6] stale 'pending' row (simulated crash) is treated as abandoned, retry allowed: OK")

        print("SMOKE TEST PASSED")
    except Exception as exc:
        print(f"SMOKE TEST FAILED: {exc!r}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up test data regardless of outcome — this may run against a
        # shared local dev database, not a disposable one.
        await pool.execute("DELETE FROM idempotency_keys WHERE scope = $1", scope)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
