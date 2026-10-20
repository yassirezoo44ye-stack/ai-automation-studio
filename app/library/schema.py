"""
Flow Library — idempotent schema initialisation.

Called once per startup from factory.py (async lifespan context).
All statements use CREATE TABLE IF NOT EXISTS so re-running is safe.

Tables:
  library_books          — unified book catalog (metadata only, no binaries)
  library_sources        — per-org source API configurations
  library_shelves        — named shelves (personal or org-level)
  library_shelf_items    — books on a shelf
  library_reading_progress — per-user progress per book
  library_search_history — search analytics
"""
from __future__ import annotations

import asyncpg


_SQL = """
-- ─── Book Catalog ─────────────────────────────────────────────────────────────
-- Central metadata store; rows are upserted from external sources on demand.
-- A single book may have entries from multiple sources; the canonical key is
-- (source, source_book_id) so duplicates don't contaminate the catalog.
CREATE TABLE IF NOT EXISTS library_books (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              VARCHAR(40) NOT NULL
                        CHECK (source IN (
                            'openlibrary','google_books','gutenberg',
                            'internet_archive','manual'
                        )),
    source_book_id      TEXT NOT NULL,
    isbn_10             VARCHAR(20),
    isbn_13             VARCHAR(20),
    title               TEXT NOT NULL,
    subtitle            TEXT,
    authors             JSONB NOT NULL DEFAULT '[]',  -- [{name, id}]
    publisher           TEXT,
    publish_year        SMALLINT,
    language            VARCHAR(10) NOT NULL DEFAULT 'en',
    description         TEXT,
    cover_url           TEXT,
    page_count          INTEGER,
    categories          JSONB NOT NULL DEFAULT '[]',  -- ["Fiction","History"]
    has_full_text       BOOLEAN NOT NULL DEFAULT FALSE,
    full_text_url       TEXT,     -- only for public-domain / openly-licensed books
    has_audio           BOOLEAN NOT NULL DEFAULT FALSE,
    audio_url           TEXT,
    license             VARCHAR(80),   -- e.g. "Public Domain", "CC BY 4.0"
    external_url        TEXT,          -- canonical URL at the source
    metadata            JSONB NOT NULL DEFAULT '{}',
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_book_id)
);
CREATE INDEX IF NOT EXISTS idx_library_books_title    ON library_books USING GIN (to_tsvector('simple', title));
CREATE INDEX IF NOT EXISTS idx_library_books_authors  ON library_books USING GIN (authors);
CREATE INDEX IF NOT EXISTS idx_library_books_lang     ON library_books (language);
CREATE INDEX IF NOT EXISTS idx_library_books_year     ON library_books (publish_year);
CREATE INDEX IF NOT EXISTS idx_library_books_fulltext ON library_books (has_full_text) WHERE has_full_text = TRUE;

-- ─── Source API Configuration ─────────────────────────────────────────────────
-- Stores per-org API credentials and on/off switches for each external source.
-- Orgs that don't configure a source still benefit from the shared catalog.
CREATE TABLE IF NOT EXISTS library_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source          VARCHAR(40) NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    api_key_enc     TEXT,   -- Fernet-encrypted; NULL = use platform default key
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, source)
);
CREATE INDEX IF NOT EXISTS idx_library_sources_org ON library_sources (organization_id);

-- ─── Personal Shelves ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS library_shelves (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_library_shelves_org  ON library_shelves (organization_id);
CREATE INDEX IF NOT EXISTS idx_library_shelves_user ON library_shelves (user_id);

-- ─── Shelf Items ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS library_shelf_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shelf_id    UUID NOT NULL REFERENCES library_shelves(id) ON DELETE CASCADE,
    book_id     UUID NOT NULL REFERENCES library_books(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes       TEXT,
    UNIQUE (shelf_id, book_id)
);
CREATE INDEX IF NOT EXISTS idx_library_shelf_items_shelf ON library_shelf_items (shelf_id);
CREATE INDEX IF NOT EXISTS idx_library_shelf_items_book  ON library_shelf_items (book_id);

-- ─── Reading Progress ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS library_reading_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id         UUID NOT NULL REFERENCES library_books(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'want_to_read'
                    CHECK (status IN ('want_to_read','reading','completed','dropped')),
    current_page    INTEGER,
    total_pages     INTEGER,
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    review          TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, book_id)
);
CREATE INDEX IF NOT EXISTS idx_library_progress_user ON library_reading_progress (user_id);
CREATE INDEX IF NOT EXISTS idx_library_progress_org  ON library_reading_progress (organization_id);
CREATE INDEX IF NOT EXISTS idx_library_progress_book ON library_reading_progress (book_id);

-- ─── Search History ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS library_search_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    query           TEXT NOT NULL,
    filters         JSONB NOT NULL DEFAULT '{}',
    result_count    INTEGER,
    searched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_library_search_org    ON library_search_history (organization_id, searched_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_search_user   ON library_search_history (user_id);
"""


async def init_library_schema(conn: asyncpg.Connection) -> None:
    """Create all library tables (idempotent)."""
    await conn.execute(_SQL)
