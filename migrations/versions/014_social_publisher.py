"""
Flow Social Publisher — Phase 1 Foundation.

Three tables, all scoped to organization_id for multi-tenant isolation:

  social_platform_accounts  — OAuth tokens per user × platform
  social_posts              — canonical post record (caption, video_url, targets)
  social_publish_jobs       — per-platform publish attempt with status tracking

Design decisions
────────────────
• Video storage: Phase 1 uses URL-based delivery (PULL_FROM_URL on TikTok,
  video_url on Instagram/YouTube).  Binary file upload is Phase 2.
• Token encryption: access_token_enc / refresh_token_enc store the raw token
  encrypted at rest via the application layer (AES-256-GCM, key from
  SOCIAL_TOKEN_ENC_KEY env var).  Never stored in plaintext.
• Idempotency: social_publish_jobs has a UNIQUE constraint on
  (post_id, platform) so the dispatcher cannot double-enqueue.
• social_posts.status is derived from jobs — kept denormalised for
  fast list queries without aggregating jobs every time.
• ON DELETE CASCADE from organizations/users follows the project convention.

Dependency chain:
    organizations (001) → users (001)
"""

SQL_UP = """
-- ── Platform account connections ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_platform_accounts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform            VARCHAR(30) NOT NULL
                        CHECK (platform IN ('tiktok', 'instagram', 'youtube')),
    -- External identity on the platform (creator_id, channel_id, ig_user_id, …)
    platform_user_id    TEXT        NOT NULL,
    platform_username   TEXT,
    platform_name       TEXT,
    -- Tokens stored encrypted at rest (AES-256-GCM via app layer)
    access_token_enc    TEXT        NOT NULL,
    refresh_token_enc   TEXT,
    token_expires_at    TIMESTAMPTZ,
    -- OAuth scopes granted (array of strings, e.g. '{video.upload,user.info.basic}')
    scopes              TEXT[]      NOT NULL DEFAULT '{}',
    -- Platform-specific extras (avatar_url, follower_count, etc.)
    metadata            JSONB       NOT NULL DEFAULT '{}',
    is_active           BOOLEAN     NOT NULL DEFAULT true,
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id, platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_spa_org_platform
    ON social_platform_accounts(organization_id, platform, is_active);
CREATE INDEX IF NOT EXISTS idx_spa_user
    ON social_platform_accounts(user_id);

-- ── Posts ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_posts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    -- Source video reference — Phase 1: URL only
    title               TEXT,
    caption             TEXT        NOT NULL DEFAULT '',
    video_url           TEXT        NOT NULL,
    thumbnail_url       TEXT,
    duration_seconds    INTEGER,
    -- Target platforms (array): ['tiktok','instagram','youtube']
    target_platforms    TEXT[]      NOT NULL DEFAULT '{}',
    -- Scheduling
    scheduled_at        TIMESTAMPTZ,           -- NULL = immediate
    -- Aggregated status (denormalised from jobs for fast list queries)
    -- 'draft' → not yet dispatched
    -- 'scheduled' → waiting for scheduled_at
    -- 'publishing' → at least one job is processing
    -- 'published' → all target platform jobs completed
    -- 'partial' → some completed, some failed
    -- 'failed' → all jobs failed
    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','scheduled','publishing',
                                          'published','partial','failed')),
    -- Tags / hashtags stored as array for filtering and analytics
    hashtags            TEXT[]      NOT NULL DEFAULT '{}',
    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sp_org_status
    ON social_posts(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_sp_org_scheduled
    ON social_posts(organization_id, scheduled_at)
    WHERE scheduled_at IS NOT NULL AND status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_sp_created
    ON social_posts(created_at DESC);

-- ── Publish jobs ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_publish_jobs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    post_id             UUID        NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
    platform            VARCHAR(30) NOT NULL
                        CHECK (platform IN ('tiktok', 'instagram', 'youtube')),
    -- Which account to publish from
    account_id          UUID        REFERENCES social_platform_accounts(id) ON DELETE SET NULL,
    -- Job lifecycle
    status              VARCHAR(20) NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','processing','completed','failed','cancelled')),
    -- Platform-assigned ID after upload (tiktok publish_id, yt video id, ig media id)
    platform_post_id    TEXT,
    -- Public URL after successful publish
    platform_url        TEXT,
    -- Error tracking
    error_code          TEXT,
    error_message       TEXT,
    retry_count         SMALLINT    NOT NULL DEFAULT 0,
    -- Timing
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    -- Platform-specific response payload
    result              JSONB,
    -- Prevent double-dispatch: one active job per post × platform at a time.
    -- A new job can be created only after the previous one reaches a terminal state.
    UNIQUE (post_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_spj_org_status
    ON social_publish_jobs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_spj_post
    ON social_publish_jobs(post_id);
CREATE INDEX IF NOT EXISTS idx_spj_queued
    ON social_publish_jobs(queued_at)
    WHERE status = 'queued';
"""

SQL_DOWN = """
DROP TABLE IF EXISTS social_publish_jobs;
DROP TABLE IF EXISTS social_posts;
DROP TABLE IF EXISTS social_platform_accounts;
"""


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
