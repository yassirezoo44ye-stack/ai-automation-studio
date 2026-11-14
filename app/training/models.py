"""
Training Studio — Pydantic request/response models.

Follows the project's convention: Pydantic models live close to the router
that uses them, with no ORM layer (queries are raw asyncpg).
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ── Courses ───────────────────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    title:              str
    description:        str | None = None
    project_id:         str | None = None
    language:           str           = "en"
    source_type:        str           = "manual"
    source_document_id: str | None = None


class CourseUpdate(BaseModel):
    title:       str | None = None
    description: str | None = None
    status:      str | None = None
    language:    str | None = None


class CourseOut(BaseModel):
    id:                 str
    organization_id:    str
    project_id:         str | None
    title:              str
    description:        str | None
    status:             str
    source_type:        str | None
    language:           str
    created_at:         str
    updated_at:         str


# ── Lessons ───────────────────────────────────────────────────────────────────

class LessonCreate(BaseModel):
    title:       str
    description: str | None = None
    position:    int           = 0


class LessonUpdate(BaseModel):
    title:       str | None = None
    description: str | None = None
    position:    int | None = None
    status:      str | None = None


class LessonOut(BaseModel):
    id:              str
    course_id:       str
    organization_id: str
    title:           str
    description:     str | None
    position:        int
    status:          str
    duration_seconds: int | None
    created_at:      str
    updated_at:      str


# ── Scripts ───────────────────────────────────────────────────────────────────

class ScriptCreate(BaseModel):
    content:      str
    language:     str = "en"
    generated_by: str = "manual"


class ScriptOut(BaseModel):
    id:              str
    lesson_id:       str | None
    organization_id: str
    content:         str
    language:        str
    generated_by:    str
    model_used:      str | None
    created_at:      str
    updated_at:      str


# ── Videos ────────────────────────────────────────────────────────────────────

class VideoCreate(BaseModel):
    title:    str | None = None
    language: str           = "en"
    provider: str           = "mock"


class VideoOut(BaseModel):
    id:               str
    lesson_id:        str | None
    organization_id:  str
    title:            str | None
    provider:         str
    provider_video_id: str | None
    status:           str
    url:              str | None
    thumbnail_url:    str | None
    duration_seconds: int | None
    language:         str
    created_at:       str
    updated_at:       str


# ── Quizzes ───────────────────────────────────────────────────────────────────

class QuizCreate(BaseModel):
    title:      str
    pass_score: int = Field(70, ge=0, le=100)


class QuestionCreate(BaseModel):
    question_text:  str
    question_type:  str           = "multiple_choice"
    options:        list[Any]     = []
    correct_answer: int | None = None
    explanation:    str | None = None
    position:       int           = 0


class QuizOut(BaseModel):
    id:              str
    lesson_id:       str | None
    organization_id: str
    title:           str
    pass_score:      int
    created_at:      str
    updated_at:      str


# ── Learners ──────────────────────────────────────────────────────────────────

class LearnerCreate(BaseModel):
    email: str
    name:  str | None = None


class LearnerOut(BaseModel):
    id:              str
    organization_id: str
    email:           str
    name:            str | None
    created_at:      str


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    id:              str
    organization_id: str
    job_type:        str
    reference_id:    str | None
    reference_type:  str | None
    status:          str
    error_message:   str | None
    created_at:      str
    started_at:      str | None
    completed_at:    str | None


# ── Course Generation ─────────────────────────────────────────────────────────

class CourseGenerateRequest(BaseModel):
    title:              str
    source_document_id: str | None = None
    language:           str           = "en"
    target_lessons:     int           = Field(5, ge=1, le=20)
    project_id:         str | None = None
