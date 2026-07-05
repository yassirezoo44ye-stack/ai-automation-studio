"""
Token and cost tracking.

Writes every AI call to `ai_usage_log` for analytics and billing.
All reads happen through the query helpers below.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.ai.models import UsageStats

log = logging.getLogger(__name__)


async def record(
    *,
    pool,
    user_id: Optional[str],
    conversation_id: Optional[str],
    stats: UsageStats,
    cached: bool = False,
) -> None:
    """Insert one row into ai_usage_log. Fails silently to never break AI calls."""
    try:
        uid  = uuid.UUID(user_id)  if user_id          else None
        cid  = uuid.UUID(conversation_id) if conversation_id else None
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ai_usage_log
                  (user_id, conversation_id, provider, model,
                   input_tokens, output_tokens, total_tokens, cost_usd,
                   cached, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                uid, cid,
                stats.provider, stats.model,
                stats.input_tokens, stats.output_tokens, stats.total_tokens,
                stats.cost_usd,
                cached,
                datetime.now(timezone.utc),
            )
    except Exception as exc:
        log.error("cost_tracker.record failed: %s", exc)


async def totals(
    *,
    pool,
    user_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> dict:
    """Return aggregate stats for a user (or all users if user_id is None)."""
    try:
        clauses = []
        args: list = []
        i = 1
        if user_id:
            clauses.append(f"user_id = ${i}")
            args.append(uuid.UUID(user_id))
            i += 1
        if since:
            clauses.append(f"created_at >= ${i}")
            args.append(since)
            i += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT
                COUNT(*)            AS calls,
                SUM(input_tokens)   AS input_tokens,
                SUM(output_tokens)  AS output_tokens,
                SUM(total_tokens)   AS total_tokens,
                SUM(cost_usd)       AS cost_usd,
                COUNT(*) FILTER (WHERE cached) AS cached_calls
            FROM ai_usage_log {where}
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else {}
    except Exception as exc:
        log.error("cost_tracker.totals failed: %s", exc)
        return {}


async def by_provider(
    *,
    pool,
    user_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> list[dict]:
    """Breakdown by provider."""
    try:
        clauses = []
        args: list = []
        i = 1
        if user_id:
            clauses.append(f"user_id = ${i}")
            args.append(uuid.UUID(user_id))
            i += 1
        if since:
            clauses.append(f"created_at >= ${i}")
            args.append(since)
            i += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT provider, model,
                   COUNT(*)          AS calls,
                   SUM(total_tokens) AS total_tokens,
                   SUM(cost_usd)     AS cost_usd
            FROM ai_usage_log {where}
            GROUP BY provider, model
            ORDER BY cost_usd DESC
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]
    except Exception as exc:
        log.error("cost_tracker.by_provider failed: %s", exc)
        return []
