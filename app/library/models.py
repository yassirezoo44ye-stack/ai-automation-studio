"""
Flow Library — Pydantic request/response models.

No ORM layer; queries are raw asyncpg following the project convention.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Book ──────────────────────────────────────────────────────────────────────

class BookOut(BaseModel):
    id:             str
    source:         str
    source_book_id: str
    isbn_10:        Optional[str]
    isbn_13:        Optional[str]
    title:          str
    subtitle:       Optional[str]
    authors:        list[dict[str, Any]]
    publisher:      Optional[str]
    publish_year:   Optional[int]
    language:       str
    description:    Optional[str]
    cover_url:      Optional[str]
    page_count:     Optional[int]
    categories:     list[str]
    has_full_text:  bool
    full_text_url:  Optional[str]
    has_audio:      bool
    audio_url:      Optional[str]
    license:        Optional[str]
    external_url:   Optional[str]
    indexed_at:     str
    updated_at:     str


class BookCreate(BaseModel):
    source:         str             = "manual"
    source_book_id: str
    title:          str
    subtitle:       Optional[str]   = None
    authors:        list[dict[str, Any]] = Field(default_factory=list)
    publisher:      Optional[str]   = None
    publish_year:   Optional[int]   = None
    language:       str             = "en"
    description:    Optional[str]   = None
    cover_url:      Optional[str]   = None
    page_count:     Optional[int]   = None
    categories:     list[str]       = Field(default_factory=list)
    has_full_text:  bool            = False
    full_text_url:  Optional[str]   = None
    has_audio:      bool            = False
    audio_url:      Optional[str]   = None
    license:        Optional[str]   = None
    external_url:   Optional[str]   = None


# ── Search ────────────────────────────────────────────────────────────────────

class BookSearchRequest(BaseModel):
    q:          str
    language:   Optional[str]   = None
    source:     Optional[str]   = None   # filter to one source
    has_full_text: bool         = False  # only books with readable text
    has_audio:  bool            = False
    page:       int             = Field(1, ge=1)
    per_page:   int             = Field(20, ge=1, le=100)


class BookSearchResult(BaseModel):
    books:      list[BookOut]
    total:      int
    page:       int
    per_page:   int
    source:     Optional[str]   # None = federated (all sources)


# ── Shelves ───────────────────────────────────────────────────────────────────

class ShelfCreate(BaseModel):
    name:        str
    description: Optional[str] = None
    is_public:   bool          = False


class ShelfUpdate(BaseModel):
    name:        Optional[str]  = None
    description: Optional[str]  = None
    is_public:   Optional[bool]  = None


class ShelfOut(BaseModel):
    id:              str
    organization_id: str
    user_id:         Optional[str]
    name:            str
    description:     Optional[str]
    is_public:       bool
    item_count:      int
    created_at:      str
    updated_at:      str


class ShelfItemCreate(BaseModel):
    book_id: str
    notes:   Optional[str] = None


class ShelfItemOut(BaseModel):
    id:      str
    shelf_id: str
    book_id: str
    added_at: str
    notes:   Optional[str]
    book:    Optional[BookOut] = None  # populated when ?embed_book=true


# ── Reading Progress ──────────────────────────────────────────────────────────

class ReadingProgressUpdate(BaseModel):
    status:        Optional[str] = None   # want_to_read | reading | completed | dropped
    current_page:  Optional[int] = None
    total_pages:   Optional[int] = None
    rating:        Optional[int] = Field(None, ge=1, le=5)
    review:        Optional[str] = None


class ReadingProgressOut(BaseModel):
    id:             str
    book_id:        str
    status:         str
    current_page:   Optional[int]
    total_pages:    Optional[int]
    rating:         Optional[int]
    review:         Optional[str]
    started_at:     Optional[str]
    completed_at:   Optional[str]
    updated_at:     str
    book:           Optional[BookOut] = None


# ── Source config ─────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    source:      str
    enabled:     bool
    has_api_key: bool
    config:      dict[str, Any]
