"""
Training Studio — FastAPI router.

All endpoints are scoped to the authenticated user's organization via
OrgContext (app/tenancy/context.py). Every DB query filters on
organization_id — IDOR protection is applied at the query level, not just
the route level, matching the project's established pattern.

Phase 1 surface:
    /api/training/courses          CRUD
    /api/training/courses/{id}/lessons  CRUD
    /api/training/lessons/{id}/scripts  CRUD
    /api/training/lessons/{id}/videos   CRUD
    /api/training/lessons/{id}/quizzes  CRUD
    /api/training/learners         CRUD
    /api/training/jobs             list / get
    /api/training/providers        list (read-only Phase 1)

Phase 2+ (not wired here yet):
    /api/training/courses/{id}/generate  — AI course generation
    /api/training/videos/{id}/generate   — video job dispatch
    /api/training/videos/{id}/localize   — localization job
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.params import Depends

from app.core.db import get_pool
from app.tenancy.context import OrgContext, org_context, require_permission
from app.training.models import (
    CourseCreate, CourseOut, CourseUpdate,
    LearnerCreate, LearnerOut,
    LessonCreate, LessonOut, LessonUpdate,
    JobOut,
    QuizCreate, QuizOut,
    QuestionCreate,
    ScriptCreate, ScriptOut,
    VideoCreate, VideoOut,
    CourseGenerateRequest,
)
from app.integrations.video import get_video_registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/training", tags=["training"])


# ── Helper: enforce org ownership before returning a resource ─────────────────

def _not_found(resource: str) -> HTTPException:
    # Return 404 for both "not found" and "wrong org" — never leak cross-org IDs.
    return HTTPException(404, f"{resource} not found")


# ─────────────────────────────────────────────────────────────────────────────
# COURSES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/courses")
async def list_courses(
    status:   Optional[str] = None,
    language: Optional[str] = None,
    limit:    int           = 50,
    offset:   int           = 0,
    ctx: OrgContext = Depends(org_context),
):
    """List courses for the authenticated org (paginated)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, project_id, title, description,
                   status, source_type, language, created_at, updated_at
              FROM training_courses
             WHERE organization_id = $1::uuid
               AND ($2::text IS NULL OR status  = $2)
               AND ($3::text IS NULL OR language = $3)
             ORDER BY created_at DESC
             LIMIT $4 OFFSET $5
            """,
            ctx.org_id, status, language, limit, offset,
        )
    return [_course_out(r) for r in rows]


@router.post("/courses", status_code=201)
async def create_course(
    req: CourseCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO training_courses
                (organization_id, project_id, title, description,
                 language, source_type, source_document_id, created_by)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::uuid)
            RETURNING id, organization_id, project_id, title, description,
                      status, source_type, language, created_at, updated_at
            """,
            ctx.org_id, req.project_id, req.title, req.description,
            req.language, req.source_type, req.source_document_id, ctx.user_id,
        )
    return _course_out(row)


@router.get("/courses/{course_id}")
async def get_course(course_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, project_id, title, description,
                   status, source_type, language, created_at, updated_at
              FROM training_courses
             WHERE id = $1::uuid AND organization_id = $2::uuid
            """,
            course_id, ctx.org_id,
        )
    if not row:
        raise _not_found("Course")
    return _course_out(row)


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: str,
    req: CourseUpdate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    async with pool.acquire() as conn:
        # Verify ownership first
        exists = await conn.fetchval(
            "SELECT 1 FROM training_courses WHERE id=$1::uuid AND organization_id=$2::uuid",
            course_id, ctx.org_id,
        )
        if not exists:
            raise _not_found("Course")
        set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
        vals = list(updates.values())
        row = await conn.fetchrow(
            f"""
            UPDATE training_courses SET {set_clause}, updated_at=NOW()
             WHERE id=$1::uuid
            RETURNING id, organization_id, project_id, title, description,
                      status, source_type, language, created_at, updated_at
            """,
            course_id, *vals,
        )
    return _course_out(row)


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM training_courses WHERE id=$1::uuid AND organization_id=$2::uuid RETURNING id",
            course_id, ctx.org_id,
        )
    if not deleted:
        raise _not_found("Course")


# ─────────────────────────────────────────────────────────────────────────────
# LESSONS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/lessons")
async def list_lessons(course_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify the course belongs to this org
        course_org = await conn.fetchval(
            "SELECT organization_id FROM training_courses WHERE id=$1::uuid",
            course_id,
        )
        if str(course_org) != ctx.org_id:
            raise _not_found("Course")
        rows = await conn.fetch(
            """
            SELECT id, course_id, organization_id, title, description,
                   position, status, duration_seconds, created_at, updated_at
              FROM training_lessons
             WHERE course_id = $1::uuid AND organization_id = $2::uuid
             ORDER BY position ASC, created_at ASC
            """,
            course_id, ctx.org_id,
        )
    return [_lesson_out(r) for r in rows]


@router.post("/courses/{course_id}/lessons", status_code=201)
async def create_lesson(
    course_id: str,
    req: LessonCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        course_org = await conn.fetchval(
            "SELECT organization_id FROM training_courses WHERE id=$1::uuid",
            course_id,
        )
        if not course_org or str(course_org) != ctx.org_id:
            raise _not_found("Course")
        row = await conn.fetchrow(
            """
            INSERT INTO training_lessons
                (course_id, organization_id, title, description, position)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING id, course_id, organization_id, title, description,
                      position, status, duration_seconds, created_at, updated_at
            """,
            course_id, ctx.org_id, req.title, req.description, req.position,
        )
    return _lesson_out(row)


@router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: str,
    req: LessonUpdate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM training_lessons WHERE id=$1::uuid AND organization_id=$2::uuid",
            lesson_id, ctx.org_id,
        )
        if not exists:
            raise _not_found("Lesson")
        set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
        row = await conn.fetchrow(
            f"""
            UPDATE training_lessons SET {set_clause}, updated_at=NOW()
             WHERE id=$1::uuid
            RETURNING id, course_id, organization_id, title, description,
                      position, status, duration_seconds, created_at, updated_at
            """,
            lesson_id, *list(updates.values()),
        )
    return _lesson_out(row)


@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson(lesson_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM training_lessons WHERE id=$1::uuid AND organization_id=$2::uuid RETURNING id",
            lesson_id, ctx.org_id,
        )
    if not deleted:
        raise _not_found("Lesson")


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lessons/{lesson_id}/scripts")
async def list_scripts(lesson_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        _assert_lesson_org(await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        ), ctx.org_id)
        rows = await conn.fetch(
            """
            SELECT id, lesson_id, organization_id, content, language,
                   generated_by, model_used, created_at, updated_at
              FROM training_scripts
             WHERE lesson_id=$1::uuid AND organization_id=$2::uuid
             ORDER BY created_at DESC
            """,
            lesson_id, ctx.org_id,
        )
    return [_script_out(r) for r in rows]


@router.post("/lessons/{lesson_id}/scripts", status_code=201)
async def create_script(
    lesson_id: str,
    req: ScriptCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        lesson_org = await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        )
        _assert_lesson_org(lesson_org, ctx.org_id)
        row = await conn.fetchrow(
            """
            INSERT INTO training_scripts
                (lesson_id, organization_id, content, language, generated_by)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING id, lesson_id, organization_id, content, language,
                      generated_by, model_used, created_at, updated_at
            """,
            lesson_id, ctx.org_id, req.content, req.language, req.generated_by,
        )
    return _script_out(row)


# ─────────────────────────────────────────────────────────────────────────────
# VIDEOS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lessons/{lesson_id}/videos")
async def list_videos(lesson_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        _assert_lesson_org(await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        ), ctx.org_id)
        rows = await conn.fetch(
            """
            SELECT id, lesson_id, organization_id, title, provider,
                   provider_video_id, status, url, thumbnail_url,
                   duration_seconds, language, created_at, updated_at
              FROM training_videos
             WHERE lesson_id=$1::uuid AND organization_id=$2::uuid
             ORDER BY created_at DESC
            """,
            lesson_id, ctx.org_id,
        )
    return [_video_out(r) for r in rows]


@router.post("/lessons/{lesson_id}/videos", status_code=201)
async def create_video(
    lesson_id: str,
    req: VideoCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        lesson_org = await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        )
        _assert_lesson_org(lesson_org, ctx.org_id)
        row = await conn.fetchrow(
            """
            INSERT INTO training_videos
                (lesson_id, organization_id, title, provider, language)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING id, lesson_id, organization_id, title, provider,
                      provider_video_id, status, url, thumbnail_url,
                      duration_seconds, language, created_at, updated_at
            """,
            lesson_id, ctx.org_id, req.title, req.provider, req.language,
        )
    return _video_out(row)


@router.get("/videos/{video_id}")
async def get_video(video_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, lesson_id, organization_id, title, provider,
                   provider_video_id, status, url, thumbnail_url,
                   duration_seconds, language, created_at, updated_at
              FROM training_videos
             WHERE id=$1::uuid AND organization_id=$2::uuid
            """,
            video_id, ctx.org_id,
        )
    if not row:
        raise _not_found("Video")
    return _video_out(row)


@router.post("/videos/{video_id}/generate", status_code=202)
async def generate_video(
    video_id: str,
    ctx: OrgContext = Depends(org_context),
):
    """
    Dispatch a video generation job using the org's configured provider
    (falls back to MockVideoProvider in Phase 1 / development).

    Phase 1: synchronous mock — updates the DB directly.
    Phase 3+: enqueue a training_job and return job_id.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        video = await conn.fetchrow(
            """
            SELECT v.id, v.organization_id, v.provider, v.language,
                   v.title, s.content AS script_content
              FROM training_videos v
              LEFT JOIN training_scripts s ON s.lesson_id = v.lesson_id
             WHERE v.id=$1::uuid AND v.organization_id=$2::uuid
             ORDER BY s.created_at DESC
             LIMIT 1
            """,
            video_id, ctx.org_id,
        )
        if not video:
            raise _not_found("Video")
        if video["provider_video_id"] if dict(video).get("provider_video_id") else None:
            pass  # already has a provider video — allow re-generation

        registry = get_video_registry()
        provider = registry.get(video["provider"]) or registry.get_default()
        script = video["script_content"] or f"Introduction to {video['title'] or 'this lesson'}"

        try:
            result = await provider.create_video(
                title=video["title"] or "Training Video",
                script=script,
                language=video["language"],
            )
        except Exception as exc:
            log.error("video generation failed for %s: %s", video_id, exc)
            await conn.execute(
                "UPDATE training_videos SET status='failed', updated_at=NOW() WHERE id=$1::uuid",
                video_id,
            )
            raise HTTPException(502, f"Video provider error: {exc}") from exc

        row = await conn.fetchrow(
            """
            UPDATE training_videos
               SET provider_video_id=$2, status=$3, url=$4,
                   thumbnail_url=$5, duration_seconds=$6,
                   metadata=$7::jsonb, updated_at=NOW()
             WHERE id=$1::uuid
            RETURNING id, lesson_id, organization_id, title, provider,
                      provider_video_id, status, url, thumbnail_url,
                      duration_seconds, language, created_at, updated_at
            """,
            video_id,
            result.provider_video_id,
            result.status.value,
            result.url,
            result.thumbnail_url,
            result.duration_seconds,
            json.dumps(result.metadata),
        )
    return _video_out(row)


# ─────────────────────────────────────────────────────────────────────────────
# QUIZZES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lessons/{lesson_id}/quizzes")
async def list_quizzes(lesson_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        _assert_lesson_org(await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        ), ctx.org_id)
        rows = await conn.fetch(
            """
            SELECT id, lesson_id, organization_id, title, pass_score, created_at, updated_at
              FROM training_quizzes
             WHERE lesson_id=$1::uuid AND organization_id=$2::uuid
             ORDER BY created_at ASC
            """,
            lesson_id, ctx.org_id,
        )
    return [_quiz_out(r) for r in rows]


@router.post("/lessons/{lesson_id}/quizzes", status_code=201)
async def create_quiz(
    lesson_id: str,
    req: QuizCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        lesson_org = await conn.fetchval(
            "SELECT organization_id FROM training_lessons WHERE id=$1::uuid", lesson_id,
        )
        _assert_lesson_org(lesson_org, ctx.org_id)
        row = await conn.fetchrow(
            """
            INSERT INTO training_quizzes (lesson_id, organization_id, title, pass_score)
            VALUES ($1::uuid, $2::uuid, $3, $4)
            RETURNING id, lesson_id, organization_id, title, pass_score, created_at, updated_at
            """,
            lesson_id, ctx.org_id, req.title, req.pass_score,
        )
    return _quiz_out(row)


@router.post("/quizzes/{quiz_id}/questions", status_code=201)
async def add_question(
    quiz_id: str,
    req: QuestionCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        quiz_org = await conn.fetchval(
            "SELECT organization_id FROM training_quizzes WHERE id=$1::uuid", quiz_id,
        )
        if not quiz_org or str(quiz_org) != ctx.org_id:
            raise _not_found("Quiz")
        row = await conn.fetchrow(
            """
            INSERT INTO training_questions
                (quiz_id, organization_id, question_text, question_type,
                 options, correct_answer, explanation, position)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8)
            RETURNING id, quiz_id, organization_id, question_text, question_type,
                      options, correct_answer, explanation, position, created_at
            """,
            quiz_id, ctx.org_id, req.question_text, req.question_type,
            json.dumps(req.options), req.correct_answer, req.explanation, req.position,
        )
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# LEARNERS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/learners")
async def list_learners(
    limit:  int = 50,
    offset: int = 0,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, email, name, created_at
              FROM training_learners
             WHERE organization_id=$1::uuid
             ORDER BY created_at DESC
             LIMIT $2 OFFSET $3
            """,
            ctx.org_id, limit, offset,
        )
    return [_learner_out(r) for r in rows]


@router.post("/learners", status_code=201)
async def create_learner(
    req: LearnerCreate,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO training_learners (organization_id, email, name)
                VALUES ($1::uuid, $2, $3)
                ON CONFLICT (organization_id, email)
                DO UPDATE SET name=EXCLUDED.name
                RETURNING id, organization_id, email, name, created_at
                """,
                ctx.org_id, req.email, req.name,
            )
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
    return _learner_out(row)


# ─────────────────────────────────────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    limit:  int           = 50,
    ctx: OrgContext = Depends(org_context),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, job_type, reference_id, reference_type,
                   status, error_message, created_at, started_at, completed_at
              FROM training_jobs
             WHERE organization_id=$1::uuid
               AND ($2::text IS NULL OR status=$2)
             ORDER BY created_at DESC
             LIMIT $3
            """,
            ctx.org_id, status, limit,
        )
    return [_job_out(r) for r in rows]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, ctx: OrgContext = Depends(org_context)):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, job_type, reference_id, reference_type,
                   status, error_message, created_at, started_at, completed_at
              FROM training_jobs
             WHERE id=$1::uuid AND organization_id=$2::uuid
            """,
            job_id, ctx.org_id,
        )
    if not row:
        raise _not_found("Job")
    return _job_out(row)


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDERS (read-only in Phase 1)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(ctx: OrgContext = Depends(org_context)):
    """Return the list of available video providers for this org."""
    registry = get_video_registry()
    return registry.list_available()


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _assert_lesson_org(lesson_org, ctx_org_id: str) -> None:
    if not lesson_org or str(lesson_org) != ctx_org_id:
        raise _not_found("Lesson")


def _ts(v) -> str:
    return v.isoformat() if v else ""


def _course_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "organization_id": str(r["organization_id"]),
        "project_id":      str(r["project_id"]) if r["project_id"] else None,
        "title":           r["title"],
        "description":     r["description"],
        "status":          r["status"],
        "source_type":     r.get("source_type"),
        "language":        r["language"],
        "created_at":      _ts(r["created_at"]),
        "updated_at":      _ts(r["updated_at"]),
    }


def _lesson_out(r) -> dict:
    return {
        "id":               str(r["id"]),
        "course_id":        str(r["course_id"]),
        "organization_id":  str(r["organization_id"]),
        "title":            r["title"],
        "description":      r["description"],
        "position":         r["position"],
        "status":           r["status"],
        "duration_seconds": r["duration_seconds"],
        "created_at":       _ts(r["created_at"]),
        "updated_at":       _ts(r["updated_at"]),
    }


def _script_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "lesson_id":       str(r["lesson_id"]) if r["lesson_id"] else None,
        "organization_id": str(r["organization_id"]),
        "content":         r["content"],
        "language":        r["language"],
        "generated_by":    r["generated_by"],
        "model_used":      r.get("model_used"),
        "created_at":      _ts(r["created_at"]),
        "updated_at":      _ts(r["updated_at"]),
    }


def _video_out(r) -> dict:
    return {
        "id":                str(r["id"]),
        "lesson_id":         str(r["lesson_id"]) if r["lesson_id"] else None,
        "organization_id":   str(r["organization_id"]),
        "title":             r.get("title"),
        "provider":          r["provider"],
        "provider_video_id": r.get("provider_video_id"),
        "status":            r["status"],
        "url":               r.get("url"),
        "thumbnail_url":     r.get("thumbnail_url"),
        "duration_seconds":  r.get("duration_seconds"),
        "language":          r["language"],
        "created_at":        _ts(r["created_at"]),
        "updated_at":        _ts(r["updated_at"]),
    }


def _quiz_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "lesson_id":       str(r["lesson_id"]) if r["lesson_id"] else None,
        "organization_id": str(r["organization_id"]),
        "title":           r["title"],
        "pass_score":      r["pass_score"],
        "created_at":      _ts(r["created_at"]),
        "updated_at":      _ts(r["updated_at"]),
    }


def _learner_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "organization_id": str(r["organization_id"]),
        "email":           r["email"],
        "name":            r.get("name"),
        "created_at":      _ts(r["created_at"]),
    }


def _job_out(r) -> dict:
    return {
        "id":              str(r["id"]),
        "organization_id": str(r["organization_id"]),
        "job_type":        r["job_type"],
        "reference_id":    str(r["reference_id"]) if r["reference_id"] else None,
        "reference_type":  r.get("reference_type"),
        "status":          r["status"],
        "error_message":   r.get("error_message"),
        "created_at":      _ts(r["created_at"]),
        "started_at":      _ts(r["started_at"]) if r.get("started_at") else None,
        "completed_at":    _ts(r["completed_at"]) if r.get("completed_at") else None,
    }
