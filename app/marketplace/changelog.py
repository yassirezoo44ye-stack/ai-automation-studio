"""
Structured "Keep a Changelog"-style entries per version.

Distinct from `marketplace_versions.changelog` (unchanged, stays the
free-text release-notes blob) — this is a categorized breakdown so the UI
can render grouped entries and future consumers can query e.g. "every
security fix across all versions" with SQL, which the text blob can't
support. Optional per version.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

CHANGELOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_changelog (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id  UUID NOT NULL REFERENCES marketplace_versions(id) ON DELETE CASCADE,
    change_type VARCHAR(20) NOT NULL CHECK (change_type IN ('added','changed','fixed','removed','security')),
    description TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mkt_changelog_version ON marketplace_changelog(version_id);
"""


async def init_changelog_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(CHANGELOG_SCHEMA)
    log.info("marketplace changelog schema initialised")


class ChangelogService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def add_entries(self, version_id: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not entries:
            return []
        async with self._pool.acquire() as conn:
            rows = []
            for i, entry in enumerate(entries):
                row = await conn.fetchrow(
                    """INSERT INTO marketplace_changelog (version_id, change_type, description, sort_order)
                       VALUES ($1,$2,$3,$4) RETURNING *""",
                    version_id, entry["change_type"], entry["description"], entry.get("sort_order", i),
                )
                rows.append(dict(row))
        return rows

    async def list_for_version(self, version_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM marketplace_changelog WHERE version_id=$1 ORDER BY sort_order",
                version_id,
            )
        return [dict(r) for r in rows]


_service: ChangelogService | None = None


def get_changelog_service(pool: asyncpg.Pool | None = None) -> ChangelogService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = ChangelogService(pool)
    return _service
