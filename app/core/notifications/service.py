"""
NotificationService — persistence + query layer for the per-user
notification inbox (notifications table, see app/tenancy/schema.py).

Scoping model: every row carries a concrete user_id. Org-wide events fan
out to one row per org member at write time (see dispatcher.py) rather
than using a shared row + per-user read-state join table — simpler
queries, and this app's organizations are small enough that per-member
fan-out is cheap.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import asyncpg

CATEGORIES = (
    "system", "workflow", "agent", "marketplace", "billing",
    "security", "deployment", "background_job", "realtime_event", "organization",
)
SEVERITIES = ("success", "info", "warning", "error")


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for key in ("id", "user_id", "organization_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    for key in ("read_at", "archived_at", "expires_at", "created_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


class NotificationService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    # ── Create ───────────────────────────────────────────────────────────────

    async def create(
        self, *, user_id: str, type_: str, title: str, message: str,
        organization_id: Optional[str] = None, category: str = "system",
        severity: str = "info", source: Optional[str] = None,
        action: Optional[dict[str, Any]] = None, dismissible: bool = True,
        expires_at: Optional[str] = None,
    ) -> dict[str, Any]:
        if category not in CATEGORIES:
            raise ValueError(f"invalid category {category!r}")
        if severity not in SEVERITIES:
            raise ValueError(f"invalid severity {severity!r}")
        import json
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO notifications
                    (user_id, organization_id, type, category, severity,
                     title, message, source, action, dismissible, expires_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                RETURNING *
                """,
                uuid.UUID(user_id),
                uuid.UUID(organization_id) if organization_id else None,
                type_, category, severity, title, message, source,
                json.dumps(action) if action is not None else None,
                dismissible, expires_at,
            )
        return _row_to_dict(row)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list(
        self, *, user_id: str, unread_only: bool = False,
        category: Optional[str] = None, severity: Optional[str] = None,
        search: Optional[str] = None, include_archived: bool = False,
        before: Optional[str] = None, limit: int = 30,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        clauses = ["user_id = $1", "(expires_at IS NULL OR expires_at > NOW())"]
        params: list[Any] = [uuid.UUID(user_id)]

        if not include_archived:
            clauses.append("archived_at IS NULL")
        if unread_only:
            clauses.append("read_status = FALSE")
        if category:
            params.append(category)
            clauses.append(f"category = ${len(params)}")
        if severity:
            params.append(severity)
            clauses.append(f"severity = ${len(params)}")
        if search:
            params.append(f"%{search}%")
            clauses.append(f"(title ILIKE ${len(params)} OR message ILIKE ${len(params)})")
        if before:
            params.append(uuid.UUID(before))
            clauses.append(
                f"created_at < (SELECT created_at FROM notifications WHERE id = ${len(params)})"
            )

        params.append(limit)
        query = (
            f"SELECT * FROM notifications WHERE {' AND '.join(clauses)} "
            f"ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [_row_to_dict(r) for r in rows]

    async def unread_count(self, *, user_id: str) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM notifications WHERE user_id=$1 AND read_status=FALSE "
                "AND archived_at IS NULL AND (expires_at IS NULL OR expires_at > NOW())",
                uuid.UUID(user_id),
            )

    # ── Mutate (all ownership-scoped by user_id — never trust the id alone) ────

    async def mark_read(self, *, user_id: str, notification_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE notifications SET read_status=TRUE, read_at=NOW() "
                "WHERE id=$1 AND user_id=$2 AND read_status=FALSE",
                uuid.UUID(notification_id), uuid.UUID(user_id),
            )
        return result.endswith(" 1")

    async def mark_all_read(self, *, user_id: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE notifications SET read_status=TRUE, read_at=NOW() "
                "WHERE user_id=$1 AND read_status=FALSE",
                uuid.UUID(user_id),
            )
        return int(result.split(" ")[-1])

    async def archive(self, *, user_id: str, notification_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE notifications SET archived_at=NOW() "
                "WHERE id=$1 AND user_id=$2 AND archived_at IS NULL",
                uuid.UUID(notification_id), uuid.UUID(user_id),
            )
        return result.endswith(" 1")

    async def delete(self, *, user_id: str, notification_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM notifications WHERE id=$1 AND user_id=$2",
                uuid.UUID(notification_id), uuid.UUID(user_id),
            )
        return result.endswith(" 1")

    # ── Preferences ──────────────────────────────────────────────────────────

    async def get_preferences(self, *, user_id: str) -> list[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT muted_categories FROM notification_preferences WHERE user_id=$1",
                uuid.UUID(user_id),
            )
        return list(row["muted_categories"]) if row else []

    async def set_preferences(self, *, user_id: str, muted_categories: list[str]) -> list[str]:
        bad = set(muted_categories) - set(CATEGORIES)
        if bad:
            raise ValueError(f"unknown categories: {bad}")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO notification_preferences (user_id, muted_categories, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET muted_categories = EXCLUDED.muted_categories, updated_at = NOW()
                """,
                uuid.UUID(user_id), muted_categories,
            )
        return muted_categories

    async def is_muted(self, *, user_id: str, category: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT muted_categories FROM notification_preferences WHERE user_id=$1",
                uuid.UUID(user_id),
            )
        return bool(row) and category in row

    async def org_member_ids(self, *, organization_id: str) -> list[str]:
        """Every active member of an org — used by the dispatcher to fan out
        an org-scoped event into one notification row per member."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id FROM organization_members "
                "WHERE organization_id=$1 AND deleted_at IS NULL",
                uuid.UUID(organization_id),
            )
        return [str(r["user_id"]) for r in rows]


# ── Singleton wiring ─────────────────────────────────────────────────────────

_service: Optional[NotificationService] = None


def get_notification_service(pool: asyncpg.Pool | None = None) -> NotificationService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = NotificationService(pool)
    return _service
