"""
Training Studio — Pydantic request/response models.

Follows the project's convention: Pydantic models live close to the router
that uses them, with no ORM layer (queries are raw asyncpg).
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Courses ───────────────────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    title:              str
    description:        Optional[str] = None
    project_id:         Optional[str] = None
    language:           str           = "en"
    source_type:        str           = "manual"
    source_document_id: Optional[str] = None


class CourseUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    status:      Optional[str] = None
    language:    Optional[str] = None


class CourseOut(BaseModel):
    id:                 str
    organization_id:    str
    project_id:         Optional[str]
    title:              str
    description:        Optional[str]
    status:             str
    source_type:        Optional[str]
    language:           str
    created_at:         str
    updated_at:         str


# ── Lessons ───────────────────────────────────────────────────────────────────

class LessonCreate(BaseModel):
    title:       str
    description: Optional[str] = None
    position:    int           = 0


class LessonUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    position:    Optional[int] = None
    status:      Optional[str] = None


class LessonOut(BaseModel):
    id:              str
    course_id:       str
    organization_id: str
    title:           str
    description:     Optional[str]
    position:        int
    status:          str
    duration_seconds: Optional[int]
    created_at:      str
    updated_at:      str


# ── Scripts ───────────────────────────────────────────────────────────────────

class ScriptCreate(BaseModel):
    content:      str
    language:     str = "en"
    generated_by: str = "manual"


class ScriptOut(BaseModel):
    id:              str
    lesson_id:       Optional[str]
    organization_id: str
    content:         str
    language:        str
    generated_by:    str
    model_used:      Optional[str]
    created_at:      str
    updated_at:      str


# ── Videos ────────────────────────────────────────────────────────────────────

class VideoCreate(BaseModel):
    title:    Optional[str] = None
    language: str           = "en"
    provider: str           = "mock"


class VideoOut(BaseModel):
    id:               str
    lesson_id:        Optional[str]
    organization_id:  str
    title:            Optional[str]
    provider:         str
    provider_video_id: Optional[str]
    status:           str
    url:              Optional[str]
    thumbnail_url:    Optional[str]
    duration_seconds: Optional[int]
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
    correct_answer: Optional[int] = None
    explanation:    Optional[str] = None
    position:       int           = 0


class QuizOut(BaseModel):
    id:              str
    lesson_id:       Optional[str]
    organization_id: str
    title:           str
    pass_score:      int
    created_at:      str
    updated_at:      str


# ── Learners ──────────────────────────────────────────────────────────────────

class LearnerCreate(BaseModel):
    email: str
    name:  Optional[str] = None


class LearnerOut(BaseModel):
    id:              str
    organization_id: str
    email:           str
    name:            Optional[str]
    created_at:      str


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    id:              str
    organization_id: str
    job_type:        str
    reference_id:    Optional[str]
    reference_type:  Optional[str]
    status:          str
    error_message:   Optional[str]
    created_at:      str
    started_at:      Optional[str]
    completed_at:    Optional[str]


# ── Course Generation ─────────────────────────────────────────────────────────

class CourseGenerateRequest(BaseModel):
    title:              str
    source_document_id: Optional[str] = None
    language:           str           = "en"
    target_lessons:     int           = Field(5, ge=1, le=20)
    project_id:         Optional[str] = None
