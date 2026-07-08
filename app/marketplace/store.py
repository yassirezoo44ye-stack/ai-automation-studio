"""
Marketplace persistence — PostgreSQL primary, JSON-file fallback.

The store keeps the exact dict shape the marketplace API has always
returned, so swapping the backend is invisible to clients.

PostgreSQL tables:
  marketplace_items      current state of every listing
  marketplace_versions   semantic-version history + changelog per item
  marketplace_reviews    one row per review
  marketplace_installs   one row per install (auditable install history)

The JSON fallback (used when no DB pool is configured — dev/tests) reuses the
original file layout under $WORKSPACES/.marketplace/.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

MARKETPLACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_items (
    id           TEXT PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    type         VARCHAR(30)  NOT NULL,
    description  TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT 'anonymous',
    version      VARCHAR(30) NOT NULL DEFAULT '1.0.0',
    pricing      VARCHAR(20) NOT NULL DEFAULT 'free',
    price_usd    NUMERIC(10,2) NOT NULL DEFAULT 0,
    tags         TEXT[] NOT NULL DEFAULT '{}',
    metadata     JSONB NOT NULL DEFAULT '{}',
    installs     INT NOT NULL DEFAULT 0,
    rating       REAL NOT NULL DEFAULT 0,
    rating_count INT NOT NULL DEFAULT 0,
    verified     BOOLEAN NOT NULL DEFAULT false,
    created_at   DOUBLE PRECISION NOT NULL,
    updated_at   DOUBLE PRECISION NOT NULL,
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_mkt_items_type ON marketplace_items(type)  WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_mkt_items_name ON marketplace_items(lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS marketplace_versions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id    TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version    VARCHAR(30) NOT NULL,
    changelog  TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id, version)
);

CREATE TABLE IF NOT EXISTS marketplace_reviews (
    id         TEXT PRIMARY KEY,
    item_id    TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    rating     REAL NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment    TEXT,
    reviewer   TEXT NOT NULL DEFAULT 'anonymous',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mkt_reviews_item ON marketplace_reviews(item_id);

CREATE TABLE IF NOT EXISTS marketplace_installs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    organization_id UUID,
    user_email      TEXT,
    version         VARCHAR(30),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mkt_installs_item ON marketplace_installs(item_id);
"""

_ITEM_COLS = (
    "id, name, type, description, author, version, pricing, price_usd, tags, "
    "metadata, installs, rating, rating_count, verified, created_at, updated_at"
)


def _row_to_item(r: asyncpg.Record) -> dict[str, Any]:
    d = dict(r)
    d["price_usd"] = float(d["price_usd"])
    d["tags"] = list(d["tags"])
    if isinstance(d.get("metadata"), str):
        d["metadata"] = json.loads(d["metadata"])
    d.pop("deleted_at", None)
    return d


class PgMarketplaceStore:
    """PostgreSQL-backed store implementing the marketplace persistence contract."""

    backend = "postgres"

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def init(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(MARKETPLACE_SCHEMA)

    # ── Items ─────────────────────────────────────────────────────────────────

    async def list_items(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_ITEM_COLS} FROM marketplace_items WHERE deleted_at IS NULL"
            )
        return [_row_to_item(r) for r in rows]

    async def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_ITEM_COLS} FROM marketplace_items "
                "WHERE id=$1 AND deleted_at IS NULL",
                item_id,
            )
        return _row_to_item(row) if row else None

    async def upsert_item(self, item: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO marketplace_items
                         (id, name, type, description, author, version, pricing,
                          price_usd, tags, metadata, installs, rating, rating_count,
                          verified, created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                       ON CONFLICT (id) DO UPDATE SET
                         name=EXCLUDED.name, description=EXCLUDED.description,
                         version=EXCLUDED.version, pricing=EXCLUDED.pricing,
                         price_usd=EXCLUDED.price_usd, tags=EXCLUDED.tags,
                         metadata=EXCLUDED.metadata, installs=EXCLUDED.installs,
                         rating=EXCLUDED.rating, rating_count=EXCLUDED.rating_count,
                         verified=EXCLUDED.verified, updated_at=EXCLUDED.updated_at,
                         deleted_at=NULL""",
                    item["id"], item["name"], item["type"], item["description"],
                    item.get("author", "anonymous"), item["version"], item["pricing"],
                    item.get("price_usd", 0.0), item.get("tags", []),
                    json.dumps(item.get("metadata", {})),
                    item.get("installs", 0), item.get("rating", 0.0),
                    item.get("rating_count", 0), item.get("verified", False),
                    item.get("created_at", time.time()), item.get("updated_at", time.time()),
                )
                # Version history (semantic versioning trail)
                await conn.execute(
                    "INSERT INTO marketplace_versions (item_id, version, changelog) "
                    "VALUES ($1,$2,$3) ON CONFLICT (item_id, version) DO NOTHING",
                    item["id"], item["version"],
                    item.get("metadata", {}).get("changelog"),
                )

    async def delete_item(self, item_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE marketplace_items SET deleted_at=NOW() "
                "WHERE id=$1 AND deleted_at IS NULL",
                item_id,
            )
        return result != "UPDATE 0"

    async def record_install(
        self, item_id: str, *, org_id: str | None = None, user_email: str | None = None,
    ) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "UPDATE marketplace_items SET installs = installs + 1, updated_at=$2 "
                    "WHERE id=$1 AND deleted_at IS NULL "
                    f"RETURNING {_ITEM_COLS}",
                    item_id, time.time(),
                )
                if row is None:
                    return None
                await conn.execute(
                    "INSERT INTO marketplace_installs (item_id, organization_id, user_email, version) "
                    "VALUES ($1,$2,$3,$4)",
                    item_id, uuid.UUID(org_id) if org_id else None, user_email, row["version"],
                )
        return _row_to_item(row)

    # ── Reviews ───────────────────────────────────────────────────────────────

    async def add_review(self, review: dict[str, Any]) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO marketplace_reviews (id, item_id, rating, comment, reviewer, created_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    review["id"], review["listing_id"], review["rating"],
                    review.get("comment"), review.get("reviewer", "anonymous"),
                    review["created_at"],
                )
                stats = await conn.fetchrow(
                    "SELECT AVG(rating) AS avg, COUNT(*) AS n "
                    "FROM marketplace_reviews WHERE item_id=$1",
                    review["listing_id"],
                )
                await conn.execute(
                    "UPDATE marketplace_items SET rating=$2, rating_count=$3, updated_at=$4 "
                    "WHERE id=$1",
                    review["listing_id"], float(stats["avg"]), int(stats["n"]), time.time(),
                )
        return review

    async def list_reviews(self, item_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, item_id AS listing_id, rating, comment, reviewer, created_at "
                "FROM marketplace_reviews WHERE item_id=$1 ORDER BY created_at DESC",
                item_id,
            )
        return [dict(r) for r in rows]

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM marketplace_items WHERE deleted_at IS NULL"
            )


class JsonMarketplaceStore:
    """Original JSON-file store, kept as the no-database fallback (dev/tests)."""

    backend = "json"

    def __init__(self) -> None:
        self._dir = Path(os.getenv("WORKSPACES", "/tmp")) / ".marketplace"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._listings_file = self._dir / "listings.json"
        self._reviews_file  = self._dir / "reviews.json"
        self._store, self._reviews = self._load()

    def _load(self) -> tuple[dict, dict]:
        try:
            store   = json.loads(self._listings_file.read_text()) if self._listings_file.exists() else {}
            reviews = json.loads(self._reviews_file.read_text())  if self._reviews_file.exists()  else {}
            return store, reviews
        except Exception:
            return {}, {}

    def _save(self) -> None:
        try:
            self._listings_file.write_text(json.dumps(self._store, indent=2))
            self._reviews_file.write_text(json.dumps(self._reviews, indent=2))
        except Exception as exc:
            log.warning("marketplace json save failed: %s", exc)

    async def init(self) -> None:
        pass

    async def list_items(self) -> list[dict[str, Any]]:
        return list(self._store.values())

    async def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        return self._store.get(item_id)

    async def upsert_item(self, item: dict[str, Any]) -> None:
        self._store[item["id"]] = item
        self._save()

    async def delete_item(self, item_id: str) -> bool:
        existed = self._store.pop(item_id, None) is not None
        self._reviews.pop(item_id, None)
        if existed:
            self._save()
        return existed

    async def record_install(
        self, item_id: str, *, org_id: str | None = None, user_email: str | None = None,
    ) -> Optional[dict[str, Any]]:
        item = self._store.get(item_id)
        if item is None:
            return None
        item["installs"] = item.get("installs", 0) + 1
        self._save()
        return item

    async def add_review(self, review: dict[str, Any]) -> dict[str, Any]:
        lid = review["listing_id"]
        self._reviews.setdefault(lid, []).append(review)
        ratings = [r["rating"] for r in self._reviews[lid]]
        self._store[lid]["rating"] = sum(ratings) / len(ratings)
        self._store[lid]["rating_count"] = len(ratings)
        self._save()
        return review

    async def list_reviews(self, item_id: str) -> list[dict[str, Any]]:
        return self._reviews.get(item_id, [])

    async def count(self) -> int:
        return len(self._store)


# ── Seed data (applied once, whichever backend is active) ────────────────────

def seed_items() -> list[dict[str, Any]]:
    now = time.time()
    return [
        {
            "id": "listing-001", "name": "Python Code Reviewer", "type": "agent",
            "description": "Automated code review agent with security scanning and style suggestions.",
            "author": "axiom-labs", "version": "1.2.0", "pricing": "free", "price_usd": 0.0,
            "tags": ["python", "code-review", "security"], "metadata": {},
            "installs": 1420, "rating": 4.7, "rating_count": 38, "verified": True,
            "created_at": now - 86400 * 10, "updated_at": now - 86400 * 2,
        },
        {
            "id": "listing-002", "name": "Glassmorphism Theme Pack", "type": "theme",
            "description": "12 polished glassmorphism UI themes for the axiomUI platform.",
            "author": "designforge", "version": "2.0.1", "pricing": "one_time", "price_usd": 9.99,
            "tags": ["theme", "glassmorphism", "dark"], "metadata": {},
            "installs": 863, "rating": 4.9, "rating_count": 21, "verified": True,
            "created_at": now - 86400 * 30, "updated_at": now - 86400 * 5,
        },
        {
            "id": "listing-003", "name": "CI/CD Workflow Bundle", "type": "workflow",
            "description": "Complete GitHub Actions + Docker deployment workflow template bundle.",
            "author": "devops-guild", "version": "1.0.0", "pricing": "free", "price_usd": 0.0,
            "tags": ["cicd", "docker", "github-actions", "devops"], "metadata": {},
            "installs": 2105, "rating": 4.5, "rating_count": 62, "verified": True,
            "created_at": now - 86400 * 45, "updated_at": now - 86400 * 1,
        },
        {
            "id": "listing-004", "name": "Arabic NLU Prompt Pack", "type": "prompt_pack",
            "description": "200+ optimized prompts for Arabic language understanding across 6 dialects.",
            "author": "nlp-collective", "version": "1.1.0", "pricing": "subscription", "price_usd": 4.99,
            "tags": ["arabic", "nlp", "prompts", "multilingual"], "metadata": {},
            "installs": 312, "rating": 4.8, "rating_count": 15, "verified": False,
            "created_at": now - 86400 * 7, "updated_at": now - 86400 * 1,
        },
    ]


# ── Singleton wiring ──────────────────────────────────────────────────────────

_store: PgMarketplaceStore | JsonMarketplaceStore | None = None


async def init_marketplace_store(pool: asyncpg.Pool | None) -> None:
    """Called from the lifespan: pick backend, create schema, seed if empty."""
    global _store
    if pool is not None:
        _store = PgMarketplaceStore(pool)
    else:
        _store = JsonMarketplaceStore()
    await _store.init()
    if await _store.count() == 0:
        for item in seed_items():
            await _store.upsert_item(item)
        log.info("marketplace seeded (%s backend)", _store.backend)


def get_marketplace_store() -> PgMarketplaceStore | JsonMarketplaceStore:
    """Return the active store; lazily falls back to JSON when lifespan hasn't run."""
    global _store
    if _store is None:
        _store = JsonMarketplaceStore()
    return _store
