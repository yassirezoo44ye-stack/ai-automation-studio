"""
Marketplace assets — the installable payload for a listing version.

Deliberately scoped down: no blob-storage/CDN system this phase (that's real
infrastructure, not "prepare infrastructure"). An asset is either inline
text/JSON content Postgres already handles fine (prompt packs, theme
JSON/CSS, small workflow definitions) or a URL to something already hosted
elsewhere. `checksum_sha256` is computed server-side from `content` at
publish time (or must be supplied by the publisher for 'url' assets) — this
is what "verify integrity" actually checks against during install.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

ASSETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version         VARCHAR(30) NOT NULL,
    asset_type      VARCHAR(30) NOT NULL DEFAULT 'inline',
    content         TEXT,
    external_url    TEXT,
    checksum_sha256 TEXT NOT NULL,
    size_bytes      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((asset_type = 'inline' AND content IS NOT NULL) OR (asset_type = 'url' AND external_url IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_mkt_assets_item ON marketplace_assets(item_id, version);
"""


async def init_assets_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(ASSETS_SCHEMA)
    log.info("marketplace assets schema initialised")


def compute_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AssetService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def add_asset(
        self, item_id: str, version: str, *,
        content: Optional[str] = None, external_url: Optional[str] = None,
        checksum_sha256: Optional[str] = None,
    ) -> dict[str, Any]:
        if content is not None:
            asset_type = "inline"
            checksum = compute_checksum(content)
            size = len(content.encode("utf-8"))
        elif external_url is not None:
            asset_type = "url"
            if not checksum_sha256:
                raise ValueError("checksum_sha256 is required for url assets")
            checksum = checksum_sha256
            size = None
        else:
            raise ValueError("either content or external_url must be provided")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO marketplace_assets
                     (item_id, version, asset_type, content, external_url, checksum_sha256, size_bytes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   RETURNING *""",
                item_id, version, asset_type, content, external_url, checksum, size,
            )
        return dict(row)

    async def get_assets(self, item_id: str, version: Optional[str] = None) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if version:
                rows = await conn.fetch(
                    "SELECT * FROM marketplace_assets WHERE item_id=$1 AND version=$2 ORDER BY created_at",
                    item_id, version,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM marketplace_assets WHERE item_id=$1 ORDER BY version, created_at",
                    item_id,
                )
        return [dict(r) for r in rows]

    async def verify_checksum(self, asset_id: str) -> bool:
        """Real check — recomputes SHA-256 over inline content and compares.
        URL-hosted assets can't be recomputed here (no fetch), so their
        stored checksum is trusted as-is (the publisher's declaration)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT asset_type, content, checksum_sha256 FROM marketplace_assets WHERE id=$1",
                uuid.UUID(str(asset_id)),
            )
        if row is None:
            return False
        if row["asset_type"] != "inline":
            return True
        return compute_checksum(row["content"]) == row["checksum_sha256"]


_service: AssetService | None = None


def get_asset_service(pool: asyncpg.Pool | None = None) -> AssetService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = AssetService(pool)
    return _service
