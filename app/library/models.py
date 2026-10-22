"""
Flow Library — Pydantic request/response models.

No ORM layer; queries are raw asyncpg following the project convention.
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ── Book ──────────────────────────────────────────────────────────────────────

class BookOut(BaseModel):
    id:             str
    source:         str
    source_book_id: str
    isbn_10:        str | None
    isbn_13:        str | None
    title:          str
    subtitle:       str | None
    authors:        list[dict[str, Any]]
    publisher:      str | None
    publish_year:   int | None
    language:       str
    description:    str | None
    cover_url:      str | None
    page_count:     int | None
    categories:     list[str]
    has_full_text:  bool
    full_text_url:  str | None
    has_audio:      bool
    audio_url:      str | None
    license:        str | None
    external_url:   str | None
    indexed_at:     str
    updated_at:     str


class BookCreate(BaseModel):
    source:         str             = "manual"
    source_book_id: str
    title:          str
    subtitle:       str | None   = None
    authors:        list[dict[str, Any]] = Field(default_factory=list)
    publisher:      str | None   = None
    publish_year:   int | None   = None
    language:       str             = "en"
    description:    str | None   = None
    cover_url:      str | None   = None
    page_count:     int | None   = None
    categories:     list[str]       = Field(default_factory=list)
    has_full_text:  bool            = False
    full_text_url:  str | None   = None
    has_audio:      bool            = False
    audio_url:      str | None   = None
    license:        str | None   = None
    external_url:   str | None   = None


# ── Search ────────────────────────────────────────────────────────────────────

class BookSearchRequest(BaseModel):
    q:          str
    language:   str | None   = None
    source:     str | None   = None   # filter to one source
    has_full_text: bool         = False  # only books with readable text
    has_audio:  bool            = False
    page:       int             = Field(1, ge=1)
    per_page:   int             = Field(20, ge=1, le=100)


class BookSearchResult(BaseModel):
    books:      list[BookOut]
    total:      int
    page:       int
    per_page:   int
    source:     str | None   # None = federated (all sources)


# ── Shelves ───────────────────────────────────────────────────────────────────

class ShelfCreate(BaseModel):
    name:        str
    description: str | None = None
    is_public:   bool          = False


class ShelfUpdate(BaseModel):
    name:        str | None  = None
    description: str | None  = None
    is_public:   bool | None  = None


class ShelfOut(BaseModel):
    id:              str
    organization_id: str
    user_id:         str | None
    name:            str
    description:     str | None
    is_public:       bool
    item_count:      int
    created_at:      str
    updated_at:      str


class ShelfItemCreate(BaseModel):
    book_id: str
    notes:   str | None = None


class ShelfItemOut(BaseModel):
    id:      str
    shelf_id: str
    book_id: str
    added_at: str
    notes:   str | None
    book:    BookOut | None = None  # populated when ?embed_book=true


# ── Reading Progress ──────────────────────────────────────────────────────────

class ReadingProgressUpdate(BaseModel):
    status:        str | None = None   # want_to_read | reading | completed | dropped
    current_page:  int | None = None
    total_pages:   int | None = None
    rating:        int | None = Field(None, ge=1, le=5)
    review:        str | None = None


class ReadingProgressOut(BaseModel):
    id:             str
    book_id:        str
    status:         str
    current_page:   int | None
    total_pages:    int | None
    rating:         int | None
    review:         str | None
    started_at:     str | None
    completed_at:   str | None
    updated_at:     str
    book:           BookOut | None = None


# ── Source config ─────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    source:      str
    enabled:     bool
    has_api_key: bool
    config:      dict[str, Any]
