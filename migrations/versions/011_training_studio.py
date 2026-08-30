"""
Training Studio — Phase 1 Foundation.

Adds 12 training tables, all scoped to organization_id for multi-tenant
isolation. Uses the project's convention: SQL_UP / SQL_DOWN strings with
up(conn) / down(conn) functions.

Dependency chain:
    organizations (001) → projects (001) → users (001)
    All FKs use ON DELETE CASCADE so dropping an org/project cleans up
    its training content automatically.
"""

SQL_UP = """
-- ─── Courses ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_courses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id          UUID REFERENCES projects(id) ON DELETE SET NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','published','archived')),
    source_type         VARCHAR(30) DEFAULT 'manual'
                        CHECK (source_type IN ('manual','document','url','ai_generated')),
    source_document_id  TEXT,
    language            VARCHAR(10) NOT NULL DEFAULT 'en',
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_courses_org     ON training_courses(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_training_courses_project ON training_courses(project_id);

-- ─── Lessons ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_lessons (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id        UUID NOT NULL REFERENCES training_courses(id) ON DELETE CASCADE,
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    description      TEXT,
    position         SMALLINT NOT NULL DEFAULT 0,
    status           VARCHAR(20) NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','published','archived')),
    duration_seconds INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_lessons_course ON training_lessons(course_id, position);
CREATE INDEX IF NOT EXISTS idx_training_lessons_org    ON training_lessons(organization_id);

-- ─── Scripts ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_scripts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id       UUID REFERENCES training_lessons(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    language        VARCHAR(10) NOT NULL DEFAULT 'en',
    generated_by    VARCHAR(30) DEFAULT 'manual'
                    CHECK (generated_by IN ('manual','ai','imported')),
    model_used      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_scripts_lesson ON training_scripts(lesson_id);
CREATE INDEX IF NOT EXISTS idx_training_scripts_org    ON training_scripts(organization_id);

-- ─── Videos ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_videos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id       UUID REFERENCES training_lessons(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT,
    provider        VARCHAR(40) NOT NULL DEFAULT 'mock',
    provider_video_id TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','queued','processing','completed','failed','cancelled')),
    url             TEXT,
    thumbnail_url   TEXT,
    duration_seconds INTEGER,
    language        VARCHAR(10) NOT NULL DEFAULT 'en',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_videos_lesson ON training_videos(lesson_id);
CREATE INDEX IF NOT EXISTS idx_training_videos_org    ON training_videos(organization_id, status);

-- ─── Video Scenes ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_video_scenes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id        UUID NOT NULL REFERENCES training_videos(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    position        SMALLINT NOT NULL DEFAULT 0,
    narration       TEXT,
    visual          TEXT,
    avatar_id       TEXT,
    voice_id        TEXT,
    duration_seconds INTEGER,
    background      TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_scenes_video ON training_video_scenes(video_id, position);

-- ─── Quizzes ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_quizzes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id       UUID REFERENCES training_lessons(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    pass_score      SMALLINT NOT NULL DEFAULT 70
                    CHECK (pass_score BETWEEN 0 AND 100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_quizzes_lesson ON training_quizzes(lesson_id);
CREATE INDEX IF NOT EXISTS idx_training_quizzes_org    ON training_quizzes(organization_id);

-- ─── Quiz Questions ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_questions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id         UUID NOT NULL REFERENCES training_quizzes(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    position        SMALLINT NOT NULL DEFAULT 0,
    question_text   TEXT NOT NULL,
    question_type   VARCHAR(30) NOT NULL DEFAULT 'multiple_choice'
                    CHECK (question_type IN ('multiple_choice','true_false','short_answer','poll')),
    options         JSONB NOT NULL DEFAULT '[]',
    correct_answer  INTEGER,
    explanation     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_questions_quiz ON training_questions(quiz_id, position);

-- ─── Localizations ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_localizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL,
    source_type     VARCHAR(30) NOT NULL
                    CHECK (source_type IN ('course','lesson','script','video','quiz','question')),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    language        VARCHAR(10) NOT NULL,
    content         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','completed','failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, source_type, language)
);
CREATE INDEX IF NOT EXISTS idx_training_loc_source ON training_localizations(source_id, source_type);
CREATE INDEX IF NOT EXISTS idx_training_loc_org    ON training_localizations(organization_id, language);

-- ─── Learners ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_learners (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    email           TEXT NOT NULL,
    name            TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, email)
);
CREATE INDEX IF NOT EXISTS idx_training_learners_org ON training_learners(organization_id);

-- ─── Enrollments ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_enrollments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    learner_id      UUID NOT NULL REFERENCES training_learners(id) ON DELETE CASCADE,
    course_id       UUID NOT NULL REFERENCES training_courses(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','completed','dropped','expired')),
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (learner_id, course_id)
);
CREATE INDEX IF NOT EXISTS idx_training_enrollments_learner ON training_enrollments(learner_id);
CREATE INDEX IF NOT EXISTS idx_training_enrollments_course  ON training_enrollments(course_id);
CREATE INDEX IF NOT EXISTS idx_training_enrollments_org     ON training_enrollments(organization_id, status);

-- ─── Progress ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id   UUID NOT NULL REFERENCES training_enrollments(id) ON DELETE CASCADE,
    lesson_id       UUID NOT NULL REFERENCES training_lessons(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'not_started'
                    CHECK (status IN ('not_started','in_progress','completed')),
    score           SMALLINT CHECK (score BETWEEN 0 AND 100),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    UNIQUE (enrollment_id, lesson_id)
);
CREATE INDEX IF NOT EXISTS idx_training_progress_enrollment ON training_progress(enrollment_id);
CREATE INDEX IF NOT EXISTS idx_training_progress_org        ON training_progress(organization_id);

-- ─── Providers ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_providers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider_id     VARCHAR(40) NOT NULL,
    display_name    TEXT NOT NULL,
    api_key_enc     TEXT,
    config          JSONB NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, provider_id)
);
CREATE INDEX IF NOT EXISTS idx_training_providers_org ON training_providers(organization_id, enabled);

-- ─── Jobs ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS training_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    job_type        VARCHAR(40) NOT NULL
                    CHECK (job_type IN ('generate_course','generate_script','generate_video',
                                        'generate_quiz','localize')),
    reference_id    UUID,
    reference_type  VARCHAR(30),
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','processing','completed','failed','cancelled')),
    payload         JSONB NOT NULL DEFAULT '{}',
    result          JSONB,
    error_message   TEXT,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_training_jobs_org    ON training_jobs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_training_jobs_ref    ON training_jobs(reference_id, reference_type);
CREATE INDEX IF NOT EXISTS idx_training_jobs_created ON training_jobs(created_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS training_jobs;
DROP TABLE IF EXISTS training_providers;
DROP TABLE IF EXISTS training_progress;
DROP TABLE IF EXISTS training_enrollments;
DROP TABLE IF EXISTS training_learners;
DROP TABLE IF EXISTS training_localizations;
DROP TABLE IF EXISTS training_questions;
DROP TABLE IF EXISTS training_quizzes;
DROP TABLE IF EXISTS training_video_scenes;
DROP TABLE IF EXISTS training_videos;
DROP TABLE IF EXISTS training_scripts;
DROP TABLE IF EXISTS training_lessons;
DROP TABLE IF EXISTS training_courses;
"""


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
