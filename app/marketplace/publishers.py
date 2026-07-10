"""
Marketplace publisher identity — links a marketplace listing to a real
organization instead of a free-text `author` string.

Verification is a manual admin action this phase (no automated KYC) — reuses
the same `require_api_key(scopes=["admin"])` gate already established for
the billing phase's admin-plan-edit endpoint.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

PUBLISHERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_publishers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE UNIQUE,
    display_name      VARCHAR(120) NOT NULL,
    verified          BOOLEAN NOT NULL DEFAULT false,
    verified_at       TIMESTAMPTZ,
    verified_by       UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def init_publishers_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(PUBLISHERS_SCHEMA)
    # Co-located here (not in store.py) so the FK target table is guaranteed
    # to exist first — this runs after marketplace_publishers is created.
    await conn.execute(
        "ALTER TABLE marketplace_items ADD COLUMN IF NOT EXISTS publisher_id "
        "UUID REFERENCES marketplace_publishers(id) ON DELETE SET NULL"
    )
    log.info("marketplace publishers schema initialised")


class PublisherService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_or_create_for_org(self, org_id: str, display_name: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO marketplace_publishers (organization_id, display_name)
                   VALUES ($1,$2)
                   ON CONFLICT (organization_id) DO UPDATE SET updated_at=NOW()
                   RETURNING *""",
                uuid.UUID(str(org_id)), display_name,
            )
        return dict(row)

    async def get(self, publisher_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM marketplace_publishers WHERE id=$1", uuid.UUID(str(publisher_id)),
            )
        return dict(row) if row else None

    async def get_by_org(self, org_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM marketplace_publishers WHERE organization_id=$1", uuid.UUID(str(org_id)),
            )
        return dict(row) if row else None

    async def link_item(self, item_id: str, publisher_id: str) -> None:
        """Stamp marketplace_items.publisher_id — a separate UPDATE because
        that column lives on a table store.py owns; store.py's own
        upsert_item() predates the publisher concept and doesn't touch it.
        `publisher_id` here is typically a dict value straight out of
        get_or_create_for_org()'s RETURNING * (an asyncpg UUID object, not a
        plain str) — str() first so uuid.UUID() doesn't choke on it."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE marketplace_items SET publisher_id=$2 WHERE id=$1",
                item_id, uuid.UUID(str(publisher_id)),
            )

    async def verify(self, publisher_id: str, *, admin_actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE marketplace_publishers
                   SET verified=true, verified_at=NOW(), verified_by=$2, updated_at=NOW()
                   WHERE id=$1 RETURNING *""",
                uuid.UUID(str(publisher_id)), uuid.UUID(str(admin_actor)) if admin_actor else None,
            )
        return dict(row) if row else None


_service: PublisherService | None = None


def get_publisher_service(pool: asyncpg.Pool | None = None) -> PublisherService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = PublisherService(pool)
    return _service
