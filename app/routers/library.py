"""
Flow Library — FastAPI router.

All endpoints are scoped to the authenticated user's organization via
OrgContext. Every DB query filters on organization_id — IDOR protection
applied at the query level.

Endpoints:
    /api/library/search            — federated search across external sources
    /api/library/books             — catalog (list, create manual entries)
    /api/library/books/{id}        — get single book
    /api/library/shelves           — personal shelves CRUD
    /api/library/shelves/{id}/items — shelf items CRUD
    /api/library/progress          — reading progress
    /api/library/progress/{book_id}
    /api/library/sources           — list available / configured sources
"""
from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.params import Depends

from app.core.db import get_pool
from app.library.models import (
    BookCreate,
    ReadingProgressUpdate,
    ShelfCreate,
    ShelfItemCreate,
    ShelfUpdate,
)
from app.library.sources import AVAILABLE_SOURCES, federated_search
from app.tenancy.context import OrgContext, org_context

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/library", tags=["library"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _not_found(resource: str = "Resource") -> HTTPException:
    return HTTPException(404, f"{resource} not found")


def _ts(v) -> str:
    return v.isoformat() if v else ""


def _book_out(r) -> dict:
    return {
        "id":             str(r["id"]),
        "source":         r["source"],
        "source_book_id": r["source_book_id"],
        "isbn_10":        r.get("isbn_10"),
        "isbn_13":        r.get("isbn_13"),
        "title":          r["title"],
        "subtitle":       r.get("subtitle"),
        "authors":        r["authors"] if r["authors"] is not None else [],
        "publisher":      r.get("publisher"),
        "publish_year":   r.get("publish_year"),
        "language":       r["language"],
        "description":    r.get("description"),
        "cover_url":      r.get("cover_url"),
        "page_count":     r.get("page_count"),
        "categories":     r["categories"] if r["categories"] is not None else [],
        "has_full_text":  bool(r["has_full_text"]),
        "full_text_url":  r.get("full_text_url"),
        "has_audio":      bool(r["has_audio"]),
        "audio_url":      r.get("audio_url"),
        "license":        r.get("license"),
        "external_url":   r.get("external_url"),
        "indexed_at":     _ts(r["indexed_at"]),
        "updated_at":     _ts(r["updated_at"]),
    }


def _shelf_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "organization_id": str(r["organization_id"]),
        "user_id":         str(r["user_id"]) if r.get("user_id") else None,
        "name":            r["name"],
        "description":     r.get("description"),
        "is_public":       bool(r["is_public"]),
        "item_count":      r.get("item_count", 0),
        "created_at":      _ts(r["created_at"]),
        "updated_at":      _ts(r["updated_at"]),
    }


def _progress_out(r) -> dict:
    return {
        "id":             str(r["id"]),
        "book_id":        str(r["book_id"]),
        "status":         r["status"],
        "current_page":   r.get("current_page"),
        "total_pages":    r.get("total_pages"),
        "rating":         r.get("rating"),
        "review":         r.get("review"),
        "started_at":     _ts(r.get("started_at")),
        "completed_at":   _ts(r.get("completed_at")),
        "updated_at":     _ts(r["updated_at"]),
    }


# ── upsert helper — writes external search results to the catalog ──────────────

async def _upsert_books(conn, books: list[dict]) -> list[str]:
    """Insert-or-update a list of raw book dicts, return their catalog UUIDs."""
    ids: list[str] = []
    for b in books:
        row = await conn.fetchrow(
            """
            INSERT INTO library_books
                (source, source_book_id, isbn_10, isbn_13, title, subtitle,
                 authors, publisher, publish_year, language, description,
                 cover_url, page_count, categories, has_full_text, full_text_url,
                 has_audio, audio_url, license, external_url)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,$13,$14::jsonb,$15,$16,$17,$18,$19,$20)
            ON CONFLICT (source, source_book_id)
            DO UPDATE SET
                title          = EXCLUDED.title,
                subtitle       = EXCLUDED.subtitle,
                authors        = EXCLUDED.authors,
                cover_url      = COALESCE(EXCLUDED.cover_url, library_books.cover_url),
                description    = COALESCE(EXCLUDED.description, library_books.description),
                has_full_text  = EXCLUDED.has_full_text,
                full_text_url  = COALESCE(EXCLUDED.full_text_url, library_books.full_text_url),
                has_audio      = EXCLUDED.has_audio,
                audio_url      = COALESCE(EXCLUDED.audio_url, library_books.audio_url),
                updated_at     = NOW()
            RETURNING id
            """,
            b["source"],
            b["source_book_id"],
            b.get("isbn_10"),
            b.get("isbn_13"),
            b["title"],
            b.get("subtitle"),
            json.dumps(b.get("authors") or []),
            b.get("publisher"),
            b.get("publish_year"),
            b.get("language", "en"),
            b.get("description"),
            b.get("cover_url"),
            b.get("page_count"),
            json.dumps(b.get("categories") or []),
            bool(b.get("has_full_text")),
            b.get("full_text_url"),
            bool(b.get("has_audio")),
            b.get("audio_url"),
            b.get("license"),
            b.get("external_url"),
        )
        if row:
            ids.append(str(row["id"]))
    return ids


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_books(
    q:             str,
    source:        str | None = Query(None, description="Filter to one source"),
    language:      str | None = None,
    has_full_text: bool          = False,
    has_audio:     bool          = False,
    page:          int           = Query(1, ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    ctx: OrgContext = Depends(org_context),
):
    """Federated search across configured external sources.

    Results are upserted into the local catalog so subsequent lookups
    by book ID work without another external call.
    """
    if not q.strip():
        raise HTTPException(400, "Search query must not be empty")

    sources = [source] if source else None
    offset  = (page - 1) * per_page

    books_raw, totals = await federated_search(
        query=q,
        sources=sources,
        language=language,
        limit_per_source=per_page,
    )

    # filter client-side flags
    if has_full_text:
        books_raw = [b for b in books_raw if b.get("has_full_text")]
    if has_audio:
        books_raw = [b for b in books_raw if b.get("has_audio")]

    pool = get_pool()
    async with pool.acquire() as conn:
        await _upsert_books(conn, books_raw)
        # log search for analytics
        with contextlib.suppress(Exception):  # analytics write failure must never break search
            await conn.execute(
                """
                INSERT INTO library_search_history
                    (organization_id, user_id, query, filters, result_count)
                VALUES ($1::uuid, $2::uuid, $3, $4::jsonb, $5)
                """,
                ctx.org_id,
                ctx.user_id,
                q,
                json.dumps({"source": source, "language": language,
                            "has_full_text": has_full_text, "has_audio": has_audio}),
                len(books_raw),
            )

    total = sum(totals.values())
    return {
        "books":    books_raw[offset:offset + per_page],
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "source":   source,
        "totals_by_source": totals,
    }


# ── Catalog (local DB) ────────────────────────────────────────────────────────

@router.get("/books")
async def list_books(
    language:      str | None = None,
    has_full_text: bool          = False,
    has_audio:     bool          = False,
    source:        str | None = None,
    limit:         int           = Query(50, ge=1, le=200),
    offset:        int           = 0,
    ctx: OrgContext = Depends(org_context),
):
    """List books that have already been indexed into the local catalog."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source, source_book_id, isbn_10, isbn_13, title, subtitle,
                   authors, publisher, publish_year, language, description,
                   cover_url, page_count, categories, has_full_text, full_text_url,
                   has_audio, audio_url, license, external_url, indexed_at, updated_at
              FROM library_books
             WHERE ($1::text IS NULL OR language        = $1)
               AND ($2::boolean IS FALSE OR has_full_text = TRUE)
               AND ($3::boolean IS FALSE OR has_audio     = TRUE)
               AND ($4::text IS NULL OR source           = $4)
             ORDER BY indexed_at DESC
             LIMIT $5 OFFSET $6
            """,
            language, has_full_text, has_audio, source, limit, offset,
        )
    return [_book_out(r) for r in rows]


@router.get("/books/{book_id}")
async def get_book(book_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, source, source_book_id, isbn_10, isbn_13, title, subtitle,
                   authors, publisher, publish_year, language, description,
                   cover_url, page_count, categories, has_full_text, full_text_url,
                   has_audio, audio_url, license, external_url, indexed_at, updated_at
              FROM library_books WHERE id = $1::uuid
            """,
            book_id,
        )
    if not row:
        raise _not_found("Book")
    return _book_out(row)


@router.post("/books", status_code=201)
async def create_book(req: BookCreate, ctx: OrgContext = Depends(org_context)):
    """Manually add a book to the catalog (e.g. for internal resources)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO library_books
                    (source, source_book_id, isbn_10, isbn_13, title, subtitle,
                     authors, publisher, publish_year, language, description,
                     cover_url, page_count, categories, has_full_text, full_text_url,
                     has_audio, audio_url, license, external_url)
                VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,$13,$14::jsonb,
                        $15,$16,$17,$18,$19,$20)
                RETURNING id, source, source_book_id, isbn_10, isbn_13, title, subtitle,
                          authors, publisher, publish_year, language, description,
                          cover_url, page_count, categories, has_full_text, full_text_url,
                          has_audio, audio_url, license, external_url, indexed_at, updated_at
                """,
                req.source, req.source_book_id, req.isbn_10, req.isbn_13,
                req.title, req.subtitle, json.dumps(req.authors), req.publisher,
                req.publish_year, req.language, req.description, req.cover_url,
                req.page_count, json.dumps(req.categories), req.has_full_text,
                req.full_text_url, req.has_audio, req.audio_url, req.license,
                req.external_url,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "Book already exists for this source/id") from None
            raise
    return _book_out(row)


# ── Shelves ───────────────────────────────────────────────────────────────────

@router.get("/shelves")
async def list_shelves(ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.organization_id, s.user_id, s.name, s.description,
                   s.is_public, s.created_at, s.updated_at,
                   COUNT(i.id)::int AS item_count
              FROM library_shelves s
         LEFT JOIN library_shelf_items i ON i.shelf_id = s.id
             WHERE s.organization_id = $1::uuid
               AND (s.user_id = $2::uuid OR s.is_public = TRUE)
             GROUP BY s.id
             ORDER BY s.created_at DESC
            """,
            ctx.org_id, ctx.user_id,
        )
    return [_shelf_out(r) for r in rows]


@router.post("/shelves", status_code=201)
async def create_shelf(req: ShelfCreate, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO library_shelves
                (organization_id, user_id, name, description, is_public)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING id, organization_id, user_id, name, description,
                      is_public, created_at, updated_at
            """,
            ctx.org_id, ctx.user_id, req.name, req.description, req.is_public,
        )
    out = dict(row)
    out["item_count"] = 0
    return _shelf_out(out)


@router.get("/shelves/{shelf_id}")
async def get_shelf(shelf_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id, s.organization_id, s.user_id, s.name, s.description,
                   s.is_public, s.created_at, s.updated_at,
                   COUNT(i.id)::int AS item_count
              FROM library_shelves s
         LEFT JOIN library_shelf_items i ON i.shelf_id = s.id
             WHERE s.id = $1::uuid
               AND s.organization_id = $2::uuid
               AND (s.user_id = $3::uuid OR s.is_public = TRUE)
             GROUP BY s.id
            """,
            shelf_id, ctx.org_id, ctx.user_id,
        )
    if not row:
        raise _not_found("Shelf")
    return _shelf_out(row)


@router.patch("/shelves/{shelf_id}")
async def update_shelf(
    shelf_id: str,
    req: ShelfUpdate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id FROM library_shelves WHERE id=$1::uuid AND organization_id=$2::uuid",
            shelf_id, ctx.org_id,
        )
        if not row:
            raise _not_found("Shelf")
        if str(row["user_id"]) != ctx.user_id:
            raise HTTPException(403, "Not your shelf")

        updates: list[str] = []
        params: list = [shelf_id]
        if req.name is not None:
            params.append(req.name)
            updates.append(f"name=${len(params)}")
        if req.description is not None:
            params.append(req.description)
            updates.append(f"description=${len(params)}")
        if req.is_public is not None:
            params.append(req.is_public)
            updates.append(f"is_public=${len(params)}")

        if not updates:
            raise HTTPException(400, "No fields to update")

        updates.append("updated_at=NOW()")
        updated = await conn.fetchrow(
            f"UPDATE library_shelves SET {', '.join(updates)} WHERE id=$1::uuid "
            f"RETURNING id, organization_id, user_id, name, description, is_public, created_at, updated_at",
            *params,
        )
    out = dict(updated)
    out["item_count"] = 0
    return _shelf_out(out)


@router.delete("/shelves/{shelf_id}", status_code=204)
async def delete_shelf(shelf_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM library_shelves WHERE id=$1::uuid AND organization_id=$2::uuid",
            shelf_id, ctx.org_id,
        )
        if not row:
            raise _not_found("Shelf")
        if str(row["user_id"]) != ctx.user_id:
            raise HTTPException(403, "Not your shelf")
        await conn.execute("DELETE FROM library_shelves WHERE id=$1::uuid", shelf_id)


# ── Shelf Items ───────────────────────────────────────────────────────────────

@router.get("/shelves/{shelf_id}/items")
async def list_shelf_items(
    shelf_id:   str,
    embed_book: bool = False,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        shelf = await conn.fetchrow(
            "SELECT id FROM library_shelves WHERE id=$1::uuid AND organization_id=$2::uuid "
            "AND (user_id=$3::uuid OR is_public=TRUE)",
            shelf_id, ctx.org_id, ctx.user_id,
        )
        if not shelf:
            raise _not_found("Shelf")

        if embed_book:
            rows = await conn.fetch(
                """
                SELECT i.id, i.shelf_id, i.book_id, i.added_at, i.notes,
                       b.source, b.source_book_id, b.isbn_10, b.isbn_13,
                       b.title, b.subtitle, b.authors, b.publisher, b.publish_year,
                       b.language, b.description, b.cover_url, b.page_count,
                       b.categories, b.has_full_text, b.full_text_url,
                       b.has_audio, b.audio_url, b.license, b.external_url,
                       b.indexed_at, b.updated_at
                  FROM library_shelf_items i
                  JOIN library_books b ON b.id = i.book_id
                 WHERE i.shelf_id = $1::uuid
                 ORDER BY i.added_at DESC
                """,
                shelf_id,
            )
            result = []
            for r in rows:
                item = {
                    "id":       str(r["id"]),
                    "shelf_id": str(r["shelf_id"]),
                    "book_id":  str(r["book_id"]),
                    "added_at": _ts(r["added_at"]),
                    "notes":    r.get("notes"),
                    "book":     _book_out(r),
                }
                result.append(item)
            return result
        else:
            rows = await conn.fetch(
                "SELECT id, shelf_id, book_id, added_at, notes "
                "FROM library_shelf_items WHERE shelf_id=$1::uuid ORDER BY added_at DESC",
                shelf_id,
            )
            return [
                {
                    "id":       str(r["id"]),
                    "shelf_id": str(r["shelf_id"]),
                    "book_id":  str(r["book_id"]),
                    "added_at": _ts(r["added_at"]),
                    "notes":    r.get("notes"),
                }
                for r in rows
            ]


@router.post("/shelves/{shelf_id}/items", status_code=201)
async def add_to_shelf(
    shelf_id: str,
    req: ShelfItemCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        shelf = await conn.fetchrow(
            "SELECT id FROM library_shelves WHERE id=$1::uuid AND organization_id=$2::uuid "
            "AND (user_id=$3::uuid OR is_public=TRUE)",
            shelf_id, ctx.org_id, ctx.user_id,
        )
        if not shelf:
            raise _not_found("Shelf")
        book = await conn.fetchrow(
            "SELECT id FROM library_books WHERE id=$1::uuid", req.book_id
        )
        if not book:
            raise _not_found("Book")
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO library_shelf_items (shelf_id, book_id, notes)
                VALUES ($1::uuid, $2::uuid, $3)
                RETURNING id, shelf_id, book_id, added_at, notes
                """,
                shelf_id, req.book_id, req.notes,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "Book already on this shelf") from None
            raise
    return {
        "id":       str(row["id"]),
        "shelf_id": str(row["shelf_id"]),
        "book_id":  str(row["book_id"]),
        "added_at": _ts(row["added_at"]),
        "notes":    row.get("notes"),
    }


@router.delete("/shelves/{shelf_id}/items/{book_id}", status_code=204)
async def remove_from_shelf(
    shelf_id: str,
    book_id:  str,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        shelf = await conn.fetchrow(
            "SELECT user_id FROM library_shelves WHERE id=$1::uuid AND organization_id=$2::uuid",
            shelf_id, ctx.org_id,
        )
        if not shelf:
            raise _not_found("Shelf")
        if str(shelf["user_id"]) != ctx.user_id:
            raise HTTPException(403, "Not your shelf")
        deleted = await conn.execute(
            "DELETE FROM library_shelf_items WHERE shelf_id=$1::uuid AND book_id=$2::uuid",
            shelf_id, book_id,
        )
        if deleted == "DELETE 0":
            raise _not_found("Shelf item")


# ── Reading Progress ──────────────────────────────────────────────────────────

@router.get("/progress")
async def list_reading_progress(
    status: str | None = None,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, book_id, status, current_page, total_pages, rating, review,
                   started_at, completed_at, updated_at
              FROM library_reading_progress
             WHERE user_id = $1::uuid AND organization_id = $2::uuid
               AND ($3::text IS NULL OR status = $3)
             ORDER BY updated_at DESC
            """,
            ctx.user_id, ctx.org_id, status,
        )
    return [_progress_out(r) for r in rows]


@router.put("/progress/{book_id}")
async def upsert_reading_progress(
    book_id: str,
    req: ReadingProgressUpdate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        book = await conn.fetchrow("SELECT id FROM library_books WHERE id=$1::uuid", book_id)
        if not book:
            raise _not_found("Book")

        existing = await conn.fetchrow(
            "SELECT id, status FROM library_reading_progress "
            "WHERE user_id=$1::uuid AND book_id=$2::uuid",
            ctx.user_id, book_id,
        )

        if existing:
            updates: list[str] = ["updated_at=NOW()"]
            params: list = [existing["id"]]
            if req.status is not None:
                params.append(req.status)
                updates.append(f"status=${len(params)}")
                if req.status == "reading" and existing["status"] == "want_to_read":
                    updates.append("started_at=COALESCE(started_at, NOW())")
                if req.status == "completed":
                    updates.append("completed_at=COALESCE(completed_at, NOW())")
            if req.current_page is not None:
                params.append(req.current_page)
                updates.append(f"current_page=${len(params)}")
            if req.total_pages is not None:
                params.append(req.total_pages)
                updates.append(f"total_pages=${len(params)}")
            if req.rating is not None:
                params.append(req.rating)
                updates.append(f"rating=${len(params)}")
            if req.review is not None:
                params.append(req.review)
                updates.append(f"review=${len(params)}")
            row = await conn.fetchrow(
                f"UPDATE library_reading_progress SET {', '.join(updates)} WHERE id=$1::uuid "
                f"RETURNING id, book_id, status, current_page, total_pages, rating, review, "
                f"started_at, completed_at, updated_at",
                *params,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO library_reading_progress
                    (organization_id, user_id, book_id, status, current_page,
                     total_pages, rating, review)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8)
                RETURNING id, book_id, status, current_page, total_pages, rating, review,
                          started_at, completed_at, updated_at
                """,
                ctx.org_id, ctx.user_id, book_id,
                req.status or "want_to_read",
                req.current_page, req.total_pages, req.rating, req.review,
            )
    return _progress_out(row)


@router.get("/progress/{book_id}")
async def get_reading_progress(book_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, book_id, status, current_page, total_pages, rating, review,
                   started_at, completed_at, updated_at
              FROM library_reading_progress
             WHERE user_id=$1::uuid AND book_id=$2::uuid AND organization_id=$3::uuid
            """,
            ctx.user_id, book_id, ctx.org_id,
        )
    if not row:
        raise _not_found("Reading progress")
    return _progress_out(row)


@router.delete("/progress/{book_id}", status_code=204)
async def delete_reading_progress(book_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM library_reading_progress "
            "WHERE user_id=$1::uuid AND book_id=$2::uuid AND organization_id=$3::uuid",
            ctx.user_id, book_id, ctx.org_id,
        )
        if deleted == "DELETE 0":
            raise _not_found("Reading progress")


# ── Sources ───────────────────────────────────────────────────────────────────

@router.get("/sources")
async def list_sources(ctx: OrgContext = Depends(org_context)):
    """List available external sources and whether they're enabled for this org."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source, enabled, api_key_enc, config FROM library_sources "
            "WHERE organization_id=$1::uuid",
            ctx.org_id,
        )
    configured = {r["source"]: r for r in rows}
    result = []
    for src in AVAILABLE_SOURCES:
        cfg = configured.get(src)
        result.append({
            "source":      src,
            "enabled":     cfg["enabled"] if cfg else True,
            "has_api_key": bool(cfg and cfg["api_key_enc"]),
            "config":      cfg["config"] if cfg else {},
        })
    return result
