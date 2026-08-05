"""
Generic request-idempotency layer — "have I already done this?" for
side-effecting operations that might be retried (client double-submit, a
job-queue retry, a webhook redelivery).

Generalizes app/billing/webhooks.py's WebhookEventService pattern (INSERT
... ON CONFLICT DO NOTHING, then check processed_at/error to distinguish a
true duplicate from a legitimate retry of unfinished work) behind a `scope`
column so multiple call sites can share one table instead of each growing
its own bespoke one — the narrower mistake
app/integrations/webhooks.py's integration_webhook_events made (a dedup_key
UNIQUE constraint with no recovery path, so a delivery that fails
mid-processing becomes a permanent stuck duplicate; see the fix alongside
this module for that specific bug).

Postgres is the source of truth — the INSERT ... ON CONFLICT is the actual
atomicity guarantee, exactly like billing_events. app.core.cache (Redis, or
the in-process fallback) is a latency optimization only, for the fast
"was this already completed" read on a cache hit — never trusted alone for
the initial claim, and any cache error is swallowed and treated as a miss.

Usage:
    async with idempotent("agent_run", f"{org_id}:{run_id}", pool=pool) as guard:
        if guard.is_replay:
            return guard.cached_result
        result = await do_the_work()
        guard.result = result
        return result

A guard that raises inside the `with` block marks the row 'failed' (not
'completed') so a future call with the same key is treated as a legitimate
retry, not a duplicate — the exception itself always propagates unchanged.

A 'pending' row is ambiguous by itself: it could mean a prior attempt
crashed before it could mark 'failed' (safe to retry now), or it could
mean another call for the exact same (scope, key) is genuinely still
running right now (must NOT also run the guarded work — that would
silently defeat the "exclusive execution" this module exists to
provide, e.g. two near-simultaneous clicks of the same button). Status
alone can't distinguish these, so a 'pending' row younger than
_STALE_PENDING_S is treated as still in-flight and raises
IdempotencyInProgress instead of being retried; older than that, the
original attempt is assumed dead and this call proceeds exactly like a
'failed' row would.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

log = logging.getLogger(__name__)

# How long a 'pending' row is trusted to mean "genuinely still running"
# before it's assumed to be an abandoned/crashed attempt safe to retry.
_STALE_PENDING_S = 300  # 5 minutes


class IdempotencyInProgress(Exception):
    """Raised when (scope, key) is claimed by another call that is still
    within _STALE_PENDING_S of having started — i.e. a genuine concurrent
    duplicate, not a crashed/abandoned attempt. Callers decide how to
    handle this (e.g. surface a 409/503 asking the client to retry
    shortly, or fail open and proceed anyway if duplication is merely
    wasteful rather than unsafe for that call site)."""


IDEMPOTENCY_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope        VARCHAR(60) NOT NULL,
    key          TEXT NOT NULL,
    status       VARCHAR(12) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','completed','failed')),
    result       JSONB,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (scope, key)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_scope_created ON idempotency_keys(scope, created_at DESC);
"""


async def init_idempotency_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(IDEMPOTENCY_SCHEMA)
    log.info("idempotency_keys schema initialised")


class IdempotencyGuard:
    """Handed to the caller's `with` block.

    Set `.result` before the block exits normally — it's what gets
    persisted and replayed on a future call with the same (scope, key).
    Leaving it None is fine for operations whose only meaningful outcome
    is "it ran"; a replay then yields cached_result=None rather than
    re-running the work, which is still correct as long as the caller
    doesn't need the value back.
    """

    __slots__ = ("is_replay", "cached_result", "result")

    def __init__(self, is_replay: bool, cached_result: Any = None) -> None:
        self.is_replay     = is_replay
        self.cached_result = cached_result
        self.result: Any   = None


def _cache_key(scope: str, key: str) -> str:
    return f"idempotency:{scope}:{key}"


@asynccontextmanager
async def idempotent(
    scope: str, key: str, *, pool: asyncpg.Pool, ttl_s: int = 86400,
) -> AsyncIterator[IdempotencyGuard]:
    """Claim (scope, key) for exclusive execution — see module docstring."""
    from app.core.cache import get_redis

    ck = _cache_key(scope, key)
    try:
        r = await get_redis()
        hit = await r.get_json(ck)
    except Exception:
        hit = None  # cache is an optimization only — a cache error is a miss
    if hit is not None:
        yield IdempotencyGuard(is_replay=True, cached_result=hit)
        return

    row = await pool.fetchrow(
        """INSERT INTO idempotency_keys (scope, key)
           VALUES ($1, $2)
           ON CONFLICT (scope, key) DO NOTHING
           RETURNING id""",
        scope, key,
    )
    if row is None:
        # Someone already claimed this key — figure out whether that
        # attempt actually finished (true duplicate), is genuinely still
        # running (concurrent duplicate — must not proceed), or is
        # unfinished/failed from a dead attempt (legitimate retry). Same
        # completed-vs-not distinction billing_events' WebhookEventService.
        # record() makes, plus the pending/stale-pending split explained
        # in the module docstring.
        existing = await pool.fetchrow(
            """SELECT status, result,
                      EXTRACT(EPOCH FROM (now() - created_at)) AS age_s
               FROM idempotency_keys WHERE scope=$1 AND key=$2""",
            scope, key,
        )
        if existing is not None and existing["status"] == "completed":
            cached_result = existing["result"]
            if isinstance(cached_result, str):
                try:
                    cached_result = json.loads(cached_result)
                except Exception:
                    pass
            try:
                r = await get_redis()
                await r.set_json(ck, cached_result, ttl=ttl_s)
            except Exception:
                pass
            yield IdempotencyGuard(is_replay=True, cached_result=cached_result)
            return
        if (existing is not None and existing["status"] == "pending"
                and existing["age_s"] is not None and existing["age_s"] < _STALE_PENDING_S):
            raise IdempotencyInProgress(
                f"({scope!r}, {key!r}) is already being processed by another "
                f"call (started {existing['age_s']:.0f}s ago) — retry shortly."
            )
        # Stale pending, or failed -> legitimate retry: reset and proceed.
        await pool.execute(
            "UPDATE idempotency_keys SET status='pending', error=NULL "
            "WHERE scope=$1 AND key=$2",
            scope, key,
        )

    guard = IdempotencyGuard(is_replay=False)
    try:
        yield guard
    except Exception as exc:
        await pool.execute(
            "UPDATE idempotency_keys SET status='failed', error=$3 "
            "WHERE scope=$1 AND key=$2",
            scope, key, str(exc)[:2000],
        )
        raise
    else:
        result_json = json.dumps(guard.result, default=str) if guard.result is not None else None
        await pool.execute(
            """UPDATE idempotency_keys
               SET status='completed', result=$3::jsonb, completed_at=now(), error=NULL
               WHERE scope=$1 AND key=$2""",
            scope, key, result_json,
        )
        if guard.result is not None:
            try:
                r = await get_redis()
                await r.set_json(ck, guard.result, ttl=ttl_s)
            except Exception:
                pass
