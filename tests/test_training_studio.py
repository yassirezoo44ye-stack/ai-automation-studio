"""
Training Studio — Gate-level tests for Phase 1.

Coverage:
  A. Schema / model layer (import-time sanity)
  B. VideoProvider ABC contract
  C. MockVideoProvider correctness
  D. VideoProviderRegistry resolution
  E. Router IDOR helpers (_not_found, _assert_lesson_org)
  F. Serializer helpers (_course_out, _lesson_out, _video_out, _script_out, etc.)
  G. factory ordering — training schema init callable
"""
from __future__ import annotations

import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── A. Model layer ──────────────────────────────────────────────────────────

class TestModels(unittest.TestCase):
    """Pydantic models import and validate correctly."""

    def test_course_create_requires_title(self):
        from app.training.models import CourseCreate
        import pydantic
        with self.assertRaises((pydantic.ValidationError, TypeError)):
            CourseCreate()  # type: ignore[call-arg]

    def test_course_create_valid(self):
        from app.training.models import CourseCreate
        c = CourseCreate(title="Intro to Flow")
        self.assertEqual(c.title, "Intro to Flow")
        self.assertEqual(c.language, "en")

    def test_lesson_create_valid(self):
        from app.training.models import LessonCreate
        l = LessonCreate(title="Lesson 1")
        self.assertEqual(l.title, "Lesson 1")
        self.assertEqual(l.position, 0)  # default is 0 (caller sets desired position)

    def test_course_generate_request_bounds(self):
        from app.training.models import CourseGenerateRequest
        import pydantic
        r = CourseGenerateRequest(title="Sales Onboarding")
        self.assertEqual(r.target_lessons, 5)
        with self.assertRaises(pydantic.ValidationError):
            CourseGenerateRequest(title="x", target_lessons=0)
        with self.assertRaises(pydantic.ValidationError):
            CourseGenerateRequest(title="x", target_lessons=21)

    def test_video_out_model(self):
        from app.training.models import VideoOut
        v = VideoOut(
            id="vid-1", lesson_id="les-1", organization_id="org-1",
            title=None, provider="mock", provider_video_id=None,
            status="draft", url=None, thumbnail_url=None,
            duration_seconds=None, language="en",
            created_at="", updated_at="",
        )
        self.assertEqual(v.provider, "mock")


# ── B. VideoProvider ABC ────────────────────────────────────────────────────

class TestVideoProviderABC(unittest.TestCase):
    """VideoProvider cannot be instantiated; concrete subclasses must."""

    def test_abc_cannot_instantiate(self):
        from app.integrations.video.base import VideoProvider
        with self.assertRaises(TypeError):
            VideoProvider()  # type: ignore[abstract]

    def test_abstract_methods_required(self):
        from app.integrations.video.base import VideoProvider
        import abc
        abstracts = {m for m in dir(VideoProvider) if getattr(getattr(VideoProvider, m, None), "__isabstractmethod__", False)}
        self.assertIn("provider_id",    abstracts)
        self.assertIn("display_name",   abstracts)
        self.assertIn("create_video",   abstracts)
        self.assertIn("get_video_status", abstracts)

    def test_is_available_defaults_true(self):
        """A concrete provider with no override should be available by default."""
        from app.integrations.video.base import VideoProvider, VideoCreateResult, VideoStatusResult, VideoStatus
        class _Concrete(VideoProvider):
            @property
            def provider_id(self): return "test"
            @property
            def display_name(self): return "Test"
            async def create_video(self, **kw): return VideoCreateResult("x", VideoStatus.COMPLETED)
            async def get_video_status(self, vid, config=None): return VideoStatusResult("x", VideoStatus.COMPLETED)
        p = _Concrete()
        self.assertTrue(p.is_available({}))

    def test_delete_video_is_noop_by_default(self):
        import asyncio
        from app.integrations.video.base import VideoProvider, VideoCreateResult, VideoStatusResult, VideoStatus
        class _Concrete(VideoProvider):
            @property
            def provider_id(self): return "test"
            @property
            def display_name(self): return "Test"
            async def create_video(self, **kw): return VideoCreateResult("x", VideoStatus.COMPLETED)
            async def get_video_status(self, vid, config=None): return VideoStatusResult("x", VideoStatus.COMPLETED)
        p = _Concrete()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(p.delete_video("vid-1"))
        finally:
            loop.close()
        self.assertIsNone(result)


# ── C. MockVideoProvider ────────────────────────────────────────────────────

class TestMockVideoProvider(unittest.TestCase):

    def setUp(self):
        from app.integrations.video.mock import MockVideoProvider
        self.provider = MockVideoProvider()

    def test_provider_id(self):
        self.assertEqual(self.provider.provider_id, "mock")

    def test_display_name(self):
        self.assertIsInstance(self.provider.display_name, str)
        self.assertGreater(len(self.provider.display_name), 0)

    def test_is_available(self):
        self.assertTrue(self.provider.is_available({}))

    def test_create_video_returns_completed(self):
        import asyncio
        from app.integrations.video.base import VideoStatus
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.provider.create_video(title="Test", script="Hello world")
            )
        finally:
            loop.close()
        self.assertEqual(result.status, VideoStatus.COMPLETED)
        self.assertIsNotNone(result.url)
        self.assertIsNotNone(result.provider_video_id)

    def test_create_video_generates_unique_ids(self):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            r1 = loop.run_until_complete(self.provider.create_video(title="A", script="S"))
            r2 = loop.run_until_complete(self.provider.create_video(title="B", script="S"))
        finally:
            loop.close()
        self.assertNotEqual(r1.provider_video_id, r2.provider_video_id)

    def test_get_video_status_returns_completed(self):
        import asyncio
        from app.integrations.video.base import VideoStatus
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.provider.get_video_status("any-id")
            )
        finally:
            loop.close()
        self.assertEqual(result.status, VideoStatus.COMPLETED)


# ── D. VideoProviderRegistry ────────────────────────────────────────────────

class TestVideoProviderRegistry(unittest.TestCase):

    def setUp(self):
        from app.integrations.video.registry import get_video_registry
        self.registry = get_video_registry()

    def test_get_mock_provider(self):
        from app.integrations.video.mock import MockVideoProvider
        p = self.registry.get("mock")
        self.assertIsInstance(p, MockVideoProvider)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.registry.get("nonexistent_provider_xyz"))

    def test_get_default_returns_provider(self):
        from app.integrations.video.base import VideoProvider
        p = self.registry.get_default()
        self.assertIsInstance(p, VideoProvider)

    def test_list_available_nonempty(self):
        items = self.registry.list_available()
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)
        self.assertIn("provider_id",   items[0])
        self.assertIn("display_name",  items[0])

    def test_list_available_includes_mock(self):
        ids = [i["provider_id"] for i in self.registry.list_available()]
        self.assertIn("mock", ids)


# ── E. Router helpers ───────────────────────────────────────────────────────

class TestRouterHelpers(unittest.TestCase):

    def test_not_found_returns_404(self):
        from app.routers.training import _not_found
        from fastapi import HTTPException
        exc = _not_found("Course")
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 404)
        self.assertIn("Course", exc.detail)

    def test_assert_lesson_org_raises_on_mismatch(self):
        from app.routers.training import _assert_lesson_org
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _assert_lesson_org("org-A", "org-B")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_assert_lesson_org_raises_on_none(self):
        from app.routers.training import _assert_lesson_org
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _assert_lesson_org(None, "org-B")

    def test_assert_lesson_org_passes_on_match(self):
        from app.routers.training import _assert_lesson_org
        # Should not raise
        _assert_lesson_org("org-A", "org-A")


# ── F. Serializer helpers ───────────────────────────────────────────────────

def _make_row(**kw):
    """Minimal asyncpg-row-like dict with .get()."""
    return kw


class TestSerializers(unittest.TestCase):

    def _ts(self):
        return datetime(2025, 1, 1, tzinfo=timezone.utc)

    def test_course_out(self):
        from app.routers.training import _course_out
        row = _make_row(
            id="c-1", organization_id="o-1", project_id=None,
            title="My Course", description="Desc",
            status="draft", source_type="manual", language="en",
            created_at=self._ts(), updated_at=self._ts(),
        )
        out = _course_out(row)
        self.assertEqual(out["id"],    "c-1")
        self.assertEqual(out["title"], "My Course")
        self.assertEqual(out["status"], "draft")
        self.assertIsNone(out["project_id"])

    def test_lesson_out(self):
        from app.routers.training import _lesson_out
        row = _make_row(
            id="l-1", course_id="c-1", organization_id="o-1",
            title="Lesson 1", description=None,
            position=1, status="draft", duration_seconds=None,
            created_at=self._ts(), updated_at=self._ts(),
        )
        out = _lesson_out(row)
        self.assertEqual(out["id"],       "l-1")
        self.assertEqual(out["position"], 1)

    def test_video_out_provider_video_id_optional(self):
        from app.routers.training import _video_out
        row = _make_row(
            id="v-1", lesson_id="l-1", organization_id="o-1",
            title="Vid", provider="mock", provider_video_id=None,
            status="draft", url=None, thumbnail_url=None,
            duration_seconds=None, language="en",
            created_at=self._ts(), updated_at=self._ts(),
        )
        out = _video_out(row)
        self.assertIsNone(out["provider_video_id"])
        self.assertEqual(out["provider"], "mock")

    def test_script_out(self):
        from app.routers.training import _script_out
        row = _make_row(
            id="s-1", lesson_id="l-1", organization_id="o-1",
            content="Hello", language="en", generated_by="manual",
            model_used=None, created_at=self._ts(), updated_at=self._ts(),
        )
        out = _script_out(row)
        self.assertEqual(out["content"], "Hello")

    def test_learner_out(self):
        from app.routers.training import _learner_out
        row = _make_row(
            id="lr-1", organization_id="o-1",
            email="test@example.com", name="Alice",
            created_at=self._ts(),
        )
        out = _learner_out(row)
        self.assertEqual(out["email"], "test@example.com")

    def test_job_out(self):
        from app.routers.training import _job_out
        row = _make_row(
            id="j-1", organization_id="o-1",
            job_type="video_generation", reference_id=None,
            reference_type=None, status="queued",
            error_message=None, created_at=self._ts(),
            started_at=None, completed_at=None,
        )
        out = _job_out(row)
        self.assertEqual(out["status"], "queued")
        self.assertIsNone(out["started_at"])


# ── G. Schema callable ──────────────────────────────────────────────────────

class TestSchemaCallable(unittest.TestCase):
    """init_training_schema is importable and is a coroutine function."""

    def test_init_training_schema_is_coroutine(self):
        import inspect
        from app.training import init_training_schema
        self.assertTrue(inspect.iscoroutinefunction(init_training_schema))

    def test_sql_up_creates_expected_tables(self):
        from app.training.schema import _SQL
        for table in [
            "training_courses", "training_lessons", "training_scripts",
            "training_videos", "training_quizzes", "training_questions",
            "training_learners", "training_enrollments", "training_progress",
            "training_jobs",
        ]:
            self.assertIn(table, _SQL, f"Expected table {table!r} not found in SQL_UP")


if __name__ == "__main__":
    unittest.main()
