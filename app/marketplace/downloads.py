"""
Marketplace download audit/analytics — distinct from marketplace_installs
(the org-activation event). A "download" fires whenever an asset's content
is actually fetched (e.g. GET /listings/{id}/assets), independent of
whether the org goes on to install it.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

DOWNLOADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_downloads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version         VARCHAR(30),
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    user_id         UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mkt_downloads_item ON marketplace_downloads(item_id, created_at DESC);
"""


async def init_downloads_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(DOWNLOADS_SCHEMA)
    log.info("marketplace downloads schema initialised")


class DownloadService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record_download(
        self, item_id: str, version: Optional[str] = None, *,
        org_id: Optional[str] = None, user_id: Optional[str] = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO marketplace_downloads (item_id, version, organization_id, user_id)
                   VALUES ($1,$2,$3,$4)""",
                item_id, version,
                uuid.UUID(str(org_id)) if org_id else None,
                uuid.UUID(str(user_id)) if user_id else None,
            )

    async def stats_for_item(self, item_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM marketplace_downloads WHERE item_id=$1", item_id,
            )
            by_version = await conn.fetch(
                """SELECT version, COUNT(*) AS count FROM marketplace_downloads
                   WHERE item_id=$1 GROUP BY version ORDER BY count DESC""",
                item_id,
            )
        return {"total": total, "by_version": [dict(r) for r in by_version]}


_service: DownloadService | None = None


def get_download_service(pool: asyncpg.Pool | None = None) -> DownloadService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = DownloadService(pool)
    return _service
