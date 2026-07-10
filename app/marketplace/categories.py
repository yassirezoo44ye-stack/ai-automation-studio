"""
Marketplace categories — structured metadata for the 8 item types.

Distinct from `store.py`'s live `type` column aggregation: this table lets
the frontend render a label/icon/description per category instead of
hardcoding an emoji lookup, without renaming or FK'ing marketplace_items.type
(which stays a free VARCHAR — no migration of existing rows required).
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

CATEGORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_categories (
    slug        VARCHAR(30) PRIMARY KEY,
    label       VARCHAR(60) NOT NULL,
    icon        VARCHAR(10),
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT true
);
"""

_SEED: tuple[dict[str, Any], ...] = (
    {"slug": "agent",       "label": "AI Agents",   "icon": "🤖", "description": "Autonomous agents for specialized tasks.",            "sort_order": 0},
    {"slug": "plugin",      "label": "Plugins",     "icon": "🧩", "description": "Extensions that add new capabilities.",                "sort_order": 1},
    {"slug": "workflow",    "label": "Workflows",   "icon": "🔀", "description": "Pre-built automation pipelines.",                      "sort_order": 2},
    {"slug": "prompt_pack", "label": "Prompt Packs","icon": "📝", "description": "Curated prompt collections.",                          "sort_order": 3},
    {"slug": "theme",       "label": "Themes",      "icon": "🎨", "description": "UI themes and visual styles.",                         "sort_order": 4},
    {"slug": "template",    "label": "Templates",   "icon": "📄", "description": "Reusable project templates.",                          "sort_order": 5},
    {"slug": "dataset",     "label": "Datasets",    "icon": "📊", "description": "Structured data for training and testing.",            "sort_order": 6},
    {"slug": "model",       "label": "Models",      "icon": "🧠", "description": "Fine-tuned or custom model configurations.",           "sort_order": 7},
)


async def init_categories_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(CATEGORIES_SCHEMA)
    for cat in _SEED:
        await conn.execute(
            """INSERT INTO marketplace_categories (slug, label, icon, description, sort_order)
               VALUES ($1,$2,$3,$4,$5) ON CONFLICT (slug) DO NOTHING""",
            cat["slug"], cat["label"], cat["icon"], cat["description"], cat["sort_order"],
        )
    log.info("marketplace categories schema initialised")


class CategoryService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def list_categories(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.slug, c.label, c.icon, c.description, c.sort_order,
                          COUNT(i.id) FILTER (WHERE i.deleted_at IS NULL) AS item_count
                   FROM marketplace_categories c
                   LEFT JOIN marketplace_items i ON i.type = c.slug
                   WHERE c.active
                   GROUP BY c.slug, c.label, c.icon, c.description, c.sort_order
                   ORDER BY c.sort_order"""
            )
        return [dict(r) for r in rows]


_service: CategoryService | None = None


def get_category_service(pool: asyncpg.Pool | None = None) -> CategoryService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = CategoryService(pool)
    return _service
