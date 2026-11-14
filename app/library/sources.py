"""
Flow Library — external source connectors.

Each connector fetches book metadata from a public API and returns
a list of dicts compatible with library_books column names.

Supported sources:
  openlibrary   — https://openlibrary.org/developers/api
  google_books  — https://developers.google.com/books
  gutenberg     — https://gutendex.com (REST wrapper for Project Gutenberg)
  internet_archive — https://archive.org/advancedsearch.php
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS = {"User-Agent": "FlowLibrary/1.0 (+https://flow.studio)"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _str(v: Any) -> str:
    return str(v) if v is not None else ""


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _year_from_date(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"\b(\d{4})\b", str(s))
    return int(m.group(1)) if m else None


# ── Open Library ──────────────────────────────────────────────────────────────

async def search_openlibrary(
    query: str,
    language: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search Open Library and return (books, total)."""
    params: dict[str, Any] = {
        "q":      query,
        "limit":  limit,
        "offset": offset,
        "fields": (
            "key,title,subtitle,author_name,first_publish_year,"
            "isbn,publisher,language,subject,cover_i,"
            "number_of_pages_median,has_fulltext,public_scan_b"
        ),
    }
    if language:
        params["language"] = language

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get("https://openlibrary.org/search.json", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("openlibrary search failed: %s", exc)
        return [], 0

    books = []
    for doc in data.get("docs", []):
        ol_key = doc.get("key", "").lstrip("/")
        if not ol_key:
            continue
        isbns = doc.get("isbn") or []
        isbn10 = next((i for i in isbns if len(i) == 10), None)
        isbn13 = next((i for i in isbns if len(i) == 13), None)
        cover_id = doc.get("cover_i")
        cover_url = (
            f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
            if cover_id else None
        )
        has_full = bool(doc.get("has_fulltext") or doc.get("public_scan_b"))
        full_url = (
            f"https://openlibrary.org/{ol_key}"
            if has_full else None
        )
        books.append({
            "source":         "openlibrary",
            "source_book_id": ol_key,
            "isbn_10":        isbn10,
            "isbn_13":        isbn13,
            "title":          doc.get("title", ""),
            "subtitle":       doc.get("subtitle"),
            "authors":        [{"name": a} for a in (doc.get("author_name") or [])],
            "publisher":      (doc.get("publisher") or [None])[0],
            "publish_year":   _int(doc.get("first_publish_year")),
            "language":       (doc.get("language") or ["en"])[0],
            "description":    None,
            "cover_url":      cover_url,
            "page_count":     _int(doc.get("number_of_pages_median")),
            "categories":     list(doc.get("subject") or [])[:10],
            "has_full_text":  has_full,
            "full_text_url":  full_url,
            "has_audio":      False,
            "audio_url":      None,
            "license":        "Public Domain" if has_full else None,
            "external_url":   f"https://openlibrary.org/{ol_key}",
        })

    total = int(data.get("numFound", 0))
    return books, total


# ── Google Books ──────────────────────────────────────────────────────────────

async def search_google_books(
    query: str,
    language: str | None = None,
    api_key: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search Google Books API and return (books, total)."""
    params: dict[str, Any] = {
        "q":          query,
        "maxResults": min(limit, 40),
        "startIndex": offset,
        "printType":  "books",
    }
    if language:
        params["langRestrict"] = language
    if api_key:
        params["key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get(
                "https://www.googleapis.com/books/v1/volumes", params=params
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("google_books search failed: %s", exc)
        return [], 0

    books = []
    for item in data.get("items") or []:
        info = item.get("volumeInfo", {})
        idents = {i.get("type"): i.get("identifier") for i in info.get("industryIdentifiers") or []}
        images = info.get("imageLinks") or {}
        access = item.get("accessInfo", {})
        epub = access.get("epub", {})
        has_full = epub.get("isAvailable", False) and epub.get("downloadLink") is not None
        books.append({
            "source":         "google_books",
            "source_book_id": item["id"],
            "isbn_10":        idents.get("ISBN_10"),
            "isbn_13":        idents.get("ISBN_13"),
            "title":          info.get("title", ""),
            "subtitle":       info.get("subtitle"),
            "authors":        [{"name": a} for a in (info.get("authors") or [])],
            "publisher":      info.get("publisher"),
            "publish_year":   _year_from_date(info.get("publishedDate")),
            "language":       info.get("language", "en"),
            "description":    info.get("description"),
            "cover_url":      images.get("thumbnail"),
            "page_count":     _int(info.get("pageCount")),
            "categories":     list(info.get("categories") or [])[:10],
            "has_full_text":  has_full,
            "full_text_url":  epub.get("downloadLink") if has_full else None,
            "has_audio":      False,
            "audio_url":      None,
            "license":        None,
            "external_url":   info.get("canonicalVolumeLink"),
        })

    total = int(data.get("totalItems", 0))
    return books, total


# ── Project Gutenberg (via Gutendex) ─────────────────────────────────────────

async def search_gutenberg(
    query: str,
    language: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search Project Gutenberg via gutendex.com and return (books, total).
    All Gutenberg books are public domain and have full text."""
    params: dict[str, Any] = {
        "search":   query,
        "page":     (offset // 32) + 1,  # gutendex paginates by 32
    }
    if language:
        params["languages"] = language

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get("https://gutendex.com/books/", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("gutenberg search failed: %s", exc)
        return [], 0

    books = []
    for item in (data.get("results") or [])[:limit]:
        gid = str(item.get("id", ""))
        formats = item.get("formats") or {}
        full_url = (
            formats.get("text/html")
            or formats.get("text/plain; charset=utf-8")
            or formats.get("text/plain")
        )
        cover_url = formats.get("image/jpeg")
        books.append({
            "source":         "gutenberg",
            "source_book_id": gid,
            "isbn_10":        None,
            "isbn_13":        None,
            "title":          item.get("title", ""),
            "subtitle":       None,
            "authors":        [{"name": p.get("name", "")} for p in (item.get("authors") or [])],
            "publisher":      "Project Gutenberg",
            "publish_year":   None,
            "language":       (item.get("languages") or ["en"])[0],
            "description":    None,
            "cover_url":      cover_url,
            "page_count":     None,
            "categories":     list(item.get("subjects") or [])[:10],
            "has_full_text":  True,
            "full_text_url":  full_url,
            "has_audio":      bool(formats.get("audio/mpeg")),
            "audio_url":      formats.get("audio/mpeg"),
            "license":        "Public Domain",
            "external_url":   f"https://www.gutenberg.org/ebooks/{gid}",
        })

    total = int(data.get("count", 0))
    return books, total


# ── Internet Archive ─────────────────────────────────────────────────────────

async def search_internet_archive(
    query: str,
    language: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search Internet Archive texts and return (books, total)."""
    fq = "mediatype:texts AND subject:book"
    if language:
        fq += f" AND language:{language}"

    params: dict[str, Any] = {
        "q":           query + f" {fq}",
        "fl[]":        "identifier,title,creator,publisher,year,language,"
                       "description,isbn,subject,imagecount",
        "rows":        limit,
        "start":       offset,
        "output":      "json",
        "sort[]":      "downloads desc",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get(
                "https://archive.org/advancedsearch.php", params=params
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("internet_archive search failed: %s", exc)
        return [], 0

    response = data.get("response", {})
    books = []
    for doc in response.get("docs") or []:
        ia_id = doc.get("identifier", "")
        if not ia_id:
            continue
        authors_raw = doc.get("creator") or []
        if isinstance(authors_raw, str):
            authors_raw = [authors_raw]
        books.append({
            "source":         "internet_archive",
            "source_book_id": ia_id,
            "isbn_10":        None,
            "isbn_13":        (doc.get("isbn") or [None])[0] if isinstance(doc.get("isbn"), list) else doc.get("isbn"),
            "title":          doc.get("title", ""),
            "subtitle":       None,
            "authors":        [{"name": a} for a in authors_raw],
            "publisher":      doc.get("publisher"),
            "publish_year":   _int(doc.get("year")),
            "language":       doc.get("language", "en"),
            "description":    doc.get("description"),
            "cover_url":      f"https://archive.org/services/img/{ia_id}",
            "page_count":     _int(doc.get("imagecount")),
            "categories":     (
                (doc.get("subject") or [])[:10]
                if isinstance(doc.get("subject"), list)
                else ([doc.get("subject")] if doc.get("subject") else [])
            ),
            "has_full_text":  True,
            "full_text_url":  f"https://archive.org/details/{ia_id}",
            "has_audio":      False,
            "audio_url":      None,
            "license":        None,
            "external_url":   f"https://archive.org/details/{ia_id}",
        })

    total = int(response.get("numFound", 0))
    return books, total


# ── Federated search ──────────────────────────────────────────────────────────

_SOURCE_FN = {
    "openlibrary":     search_openlibrary,
    "google_books":    search_google_books,
    "gutenberg":       search_gutenberg,
    "internet_archive": search_internet_archive,
}

AVAILABLE_SOURCES = list(_SOURCE_FN.keys())


async def federated_search(
    query: str,
    sources: list[str] | None = None,
    language: str | None = None,
    limit_per_source: int = 10,
    google_api_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Search all (or specified) sources concurrently.

    Returns (merged_books, {source: total_count}).
    """
    if sources is None:
        sources = AVAILABLE_SOURCES

    async def _fetch(src: str) -> tuple[str, list[dict], int]:
        fn = _SOURCE_FN.get(src)
        if fn is None:
            return src, [], 0
        kwargs: dict[str, Any] = {
            "query": query,
            "language": language,
            "limit": limit_per_source,
        }
        if src == "google_books" and google_api_key:
            kwargs["api_key"] = google_api_key
        try:
            books, total = await fn(**kwargs)
            return src, books, total
        except Exception as exc:
            logger.warning("federated_search source=%s error=%s", src, exc)
            return src, [], 0

    results = await asyncio.gather(*[_fetch(s) for s in sources])

    merged: list[dict] = []
    totals: dict[str, int] = {}
    for src, books, total in results:
        merged.extend(books)
        totals[src] = total

    return merged, totals
