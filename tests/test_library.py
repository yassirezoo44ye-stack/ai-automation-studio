"""
Flow Library — gate-level tests (no DB, no external HTTP).

Coverage:
  A. Schema / model layer (import-time sanity)
  B. Pydantic model validation
  C. Source connector helpers (_str, _int, _year_from_date)
  D. Source result structure — unit-test the raw data shaping
  E. Router helpers (_not_found, _ts, _book_out, _shelf_out, _progress_out)
  F. Federated search fan-out (mocked)
  G. init_library_schema is a coroutine function
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── A. Schema import ──────────────────────────────────────────────────────────

class TestSchemaImport(unittest.TestCase):

    def test_init_library_schema_is_coroutine(self):
        import inspect
        from app.library import init_library_schema
        self.assertTrue(inspect.iscoroutinefunction(init_library_schema))

    def test_sql_contains_expected_tables(self):
        from app.library.schema import _SQL
        for table in [
            "library_books",
            "library_sources",
            "library_shelves",
            "library_shelf_items",
            "library_reading_progress",
            "library_search_history",
        ]:
            self.assertIn(table, _SQL, f"Expected table {table!r} not in _SQL")

    def test_sql_is_idempotent(self):
        from app.library.schema import _SQL
        self.assertIn("IF NOT EXISTS", _SQL)

    def test_sql_has_conflict_key_on_books(self):
        from app.library.schema import _SQL
        self.assertIn("UNIQUE (source, source_book_id)", _SQL)


# ── B. Pydantic model validation ──────────────────────────────────────────────

class TestModels(unittest.TestCase):

    def test_book_create_defaults(self):
        from app.library.models import BookCreate
        b = BookCreate(source_book_id="OL123", title="Test Book")
        self.assertEqual(b.source, "manual")
        self.assertEqual(b.language, "en")
        self.assertFalse(b.has_full_text)
        self.assertFalse(b.has_audio)

    def test_book_create_full(self):
        from app.library.models import BookCreate
        b = BookCreate(
            source="gutenberg",
            source_book_id="1234",
            title="Pride and Prejudice",
            authors=[{"name": "Jane Austen"}],
            has_full_text=True,
            full_text_url="https://gutenberg.org/ebooks/1234",
            license="Public Domain",
        )
        self.assertEqual(b.source, "gutenberg")
        self.assertTrue(b.has_full_text)
        self.assertEqual(b.authors[0]["name"], "Jane Austen")

    def test_shelf_create_defaults(self):
        from app.library.models import ShelfCreate
        s = ShelfCreate(name="My Reading List")
        self.assertFalse(s.is_public)
        self.assertIsNone(s.description)

    def test_reading_progress_rating_bounds(self):
        import pydantic
        from app.library.models import ReadingProgressUpdate
        with self.assertRaises(pydantic.ValidationError):
            ReadingProgressUpdate(rating=0)
        with self.assertRaises(pydantic.ValidationError):
            ReadingProgressUpdate(rating=6)
        p = ReadingProgressUpdate(rating=5)
        self.assertEqual(p.rating, 5)

    def test_book_search_request_defaults(self):
        from app.library.models import BookSearchRequest
        r = BookSearchRequest(q="Python programming")
        self.assertEqual(r.page, 1)
        self.assertEqual(r.per_page, 20)
        self.assertFalse(r.has_full_text)

    def test_book_search_per_page_max(self):
        import pydantic
        from app.library.models import BookSearchRequest
        with self.assertRaises(pydantic.ValidationError):
            BookSearchRequest(q="x", per_page=101)

    def test_source_out_model(self):
        from app.library.models import SourceOut
        s = SourceOut(source="openlibrary", enabled=True, has_api_key=False, config={})
        self.assertEqual(s.source, "openlibrary")


# ── C. Source helpers ─────────────────────────────────────────────────────────

class TestSourceHelpers(unittest.TestCase):

    def test_str_converts_int(self):
        from app.library.sources import _str
        self.assertEqual(_str(42), "42")
        self.assertEqual(_str(None), "")

    def test_int_converts(self):
        from app.library.sources import _int
        self.assertEqual(_int("2023"), 2023)
        self.assertIsNone(_int(None))
        self.assertIsNone(_int("bad"))

    def test_year_from_date(self):
        from app.library.sources import _year_from_date
        self.assertEqual(_year_from_date("2023-05-01"), 2023)
        self.assertEqual(_year_from_date("1984"), 1984)
        self.assertIsNone(_year_from_date(None))
        self.assertIsNone(_year_from_date("no-year-here"))

    def test_available_sources_list(self):
        from app.library.sources import AVAILABLE_SOURCES
        self.assertIn("openlibrary",      AVAILABLE_SOURCES)
        self.assertIn("google_books",     AVAILABLE_SOURCES)
        self.assertIn("gutenberg",        AVAILABLE_SOURCES)
        self.assertIn("internet_archive", AVAILABLE_SOURCES)


# ── D. Source result shaping ──────────────────────────────────────────────────

class TestOpenLibraryShaping(unittest.IsolatedAsyncioTestCase):

    async def test_returns_empty_on_http_error(self):
        from app.library import sources
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            mock_cls.return_value = mock_client
            books, total = await sources.search_openlibrary("test query")
        self.assertEqual(books, [])
        self.assertEqual(total, 0)

    async def test_maps_doc_to_expected_fields(self):
        from app.library import sources
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "numFound": 1,
            "docs": [{
                "key": "/works/OL1W",
                "title": "Dune",
                "author_name": ["Frank Herbert"],
                "first_publish_year": 1965,
                "language": ["eng"],
                "cover_i": 12345,
                "has_fulltext": True,
                "public_scan_b": True,
            }],
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client
            books, total = await sources.search_openlibrary("dune")

        self.assertEqual(len(books), 1)
        b = books[0]
        self.assertEqual(b["source"],         "openlibrary")
        self.assertEqual(b["title"],          "Dune")
        self.assertEqual(b["authors"][0]["name"], "Frank Herbert")
        self.assertEqual(b["publish_year"],   1965)
        self.assertTrue(b["has_full_text"])
        self.assertIsNotNone(b["cover_url"])
        self.assertEqual(total, 1)


class TestGutenbergShaping(unittest.IsolatedAsyncioTestCase):

    async def test_maps_to_expected_fields(self):
        from app.library import sources
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "count": 50,
            "results": [{
                "id": 11,
                "title": "Alice's Adventures in Wonderland",
                "authors": [{"name": "Carroll, Lewis", "birth_year": 1832}],
                "languages": ["en"],
                "subjects": ["Fantasy"],
                "formats": {
                    "text/html": "https://www.gutenberg.org/files/11/11-h/11-h.htm",
                    "image/jpeg": "https://www.gutenberg.org/cache/epub/11/pg11.cover.medium.jpg",
                },
            }],
        }
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client
            books, total = await sources.search_gutenberg("alice")

        self.assertEqual(len(books), 1)
        b = books[0]
        self.assertEqual(b["source"], "gutenberg")
        self.assertEqual(b["source_book_id"], "11")
        self.assertTrue(b["has_full_text"])
        self.assertEqual(b["license"], "Public Domain")
        self.assertEqual(total, 50)


# ── E. Router helpers ─────────────────────────────────────────────────────────

class TestRouterHelpers(unittest.TestCase):

    def test_not_found_returns_404(self):
        from app.routers.library import _not_found
        from fastapi import HTTPException
        exc = _not_found("Book")
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 404)
        self.assertIn("Book", exc.detail)

    def test_not_found_default_message(self):
        from app.routers.library import _not_found
        exc = _not_found()
        self.assertEqual(exc.status_code, 404)

    def test_ts_formats_datetime(self):
        from app.routers.library import _ts
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = _ts(dt)
        self.assertIn("2025", result)

    def test_ts_returns_empty_for_none(self):
        from app.routers.library import _ts
        self.assertEqual(_ts(None), "")

    def _ts(self):
        return datetime(2025, 1, 1, tzinfo=timezone.utc)

    def _make_book_row(self):
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "source": "gutenberg",
            "source_book_id": "11",
            "isbn_10": None,
            "isbn_13": None,
            "title": "Alice in Wonderland",
            "subtitle": None,
            "authors": [{"name": "Lewis Carroll"}],
            "publisher": "Project Gutenberg",
            "publish_year": 1865,
            "language": "en",
            "description": "A classic tale.",
            "cover_url": "https://example.com/cover.jpg",
            "page_count": 96,
            "categories": ["Fiction"],
            "has_full_text": True,
            "full_text_url": "https://gutenberg.org/ebooks/11",
            "has_audio": False,
            "audio_url": None,
            "license": "Public Domain",
            "external_url": "https://gutenberg.org/ebooks/11",
            "indexed_at": self._ts(),
            "updated_at": self._ts(),
        }

    def test_book_out_all_fields(self):
        from app.routers.library import _book_out
        row = self._make_book_row()
        out = _book_out(row)
        self.assertEqual(out["id"],            "00000000-0000-0000-0000-000000000001")
        self.assertEqual(out["source"],        "gutenberg")
        self.assertEqual(out["title"],         "Alice in Wonderland")
        self.assertTrue(out["has_full_text"])
        self.assertEqual(out["license"],       "Public Domain")
        self.assertIsInstance(out["authors"],  list)
        self.assertIn("2025", out["indexed_at"])

    def test_book_out_none_authors_becomes_list(self):
        from app.routers.library import _book_out
        row = self._make_book_row()
        row["authors"] = None
        out = _book_out(row)
        self.assertEqual(out["authors"], [])

    def test_book_out_none_categories_becomes_list(self):
        from app.routers.library import _book_out
        row = self._make_book_row()
        row["categories"] = None
        out = _book_out(row)
        self.assertEqual(out["categories"], [])

    def test_shelf_out(self):
        from app.routers.library import _shelf_out
        row = {
            "id":              "00000000-0000-0000-0000-000000000002",
            "organization_id": "00000000-0000-0000-0000-000000000003",
            "user_id":         "00000000-0000-0000-0000-000000000004",
            "name":            "My Shelf",
            "description":     None,
            "is_public":       False,
            "item_count":      3,
            "created_at":      self._ts(),
            "updated_at":      self._ts(),
        }
        out = _shelf_out(row)
        self.assertEqual(out["name"],       "My Shelf")
        self.assertEqual(out["item_count"], 3)
        self.assertFalse(out["is_public"])

    def test_progress_out(self):
        from app.routers.library import _progress_out
        row = {
            "id":           "00000000-0000-0000-0000-000000000005",
            "book_id":      "00000000-0000-0000-0000-000000000001",
            "status":       "reading",
            "current_page": 42,
            "total_pages":  300,
            "rating":       None,
            "review":       None,
            "started_at":   self._ts(),
            "completed_at": None,
            "updated_at":   self._ts(),
        }
        out = _progress_out(row)
        self.assertEqual(out["status"],       "reading")
        self.assertEqual(out["current_page"], 42)
        self.assertIsNone(out["rating"])


# ── F. Federated search fan-out ───────────────────────────────────────────────

class TestFederatedSearch(unittest.IsolatedAsyncioTestCase):

    async def test_all_sources_called_concurrently(self):
        from app.library import sources

        call_log = []

        async def _fake_ol(**kw):
            call_log.append("openlibrary")
            return [{"source": "openlibrary", "title": "OL Book"}], 1

        async def _fake_gb(**kw):
            call_log.append("google_books")
            return [], 0

        async def _fake_gt(**kw):
            call_log.append("gutenberg")
            return [], 0

        async def _fake_ia(**kw):
            call_log.append("internet_archive")
            return [], 0

        fake_fns = {
            "openlibrary":      _fake_ol,
            "google_books":     _fake_gb,
            "gutenberg":        _fake_gt,
            "internet_archive": _fake_ia,
        }
        with patch.dict(sources._SOURCE_FN, fake_fns):
            merged, totals = await sources.federated_search("dune")

        self.assertCountEqual(call_log, ["openlibrary", "google_books", "gutenberg", "internet_archive"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(totals["openlibrary"], 1)
        self.assertEqual(totals["google_books"], 0)

    async def test_source_error_does_not_stop_others(self):
        from app.library import sources

        async def _fail(**kw):
            raise RuntimeError("source down")

        async def _ok(**kw):
            return [{"source": "gutenberg", "title": "Free Book"}], 5

        fake_fns = {
            "openlibrary":      _fail,
            "google_books":     _fail,
            "gutenberg":        _ok,
            "internet_archive": _fail,
        }
        with patch.dict(sources._SOURCE_FN, fake_fns):
            merged, totals = await sources.federated_search("test")

        self.assertEqual(len(merged), 1)
        self.assertEqual(totals["gutenberg"], 5)
        self.assertEqual(totals["openlibrary"], 0)

    async def test_single_source_filter(self):
        from app.library import sources

        called = []

        async def _fake(**kw):
            called.append("openlibrary")
            return [], 0

        with patch.dict(sources._SOURCE_FN, {"openlibrary": _fake}):
            await sources.federated_search("x", sources=["openlibrary"])

        self.assertEqual(called, ["openlibrary"])


# ── G. factory callable ───────────────────────────────────────────────────────

class TestSchemaCallable(unittest.TestCase):

    def test_init_library_schema_importable(self):
        from app.library import init_library_schema
        self.assertIsNotNone(init_library_schema)

    def test_init_library_schema_is_async(self):
        import inspect
        from app.library import init_library_schema
        self.assertTrue(inspect.iscoroutinefunction(init_library_schema))


if __name__ == "__main__":
    unittest.main(verbosity=2)
