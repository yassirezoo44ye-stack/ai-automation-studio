"""Organization-scoped review and handoff; never publishes to external services."""

SQL = """
CREATE TABLE IF NOT EXISTS study_content_workflows (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
 lesson_slug VARCHAR(80) NOT NULL REFERENCES study_lessons(slug) ON DELETE CASCADE,
 source_sha256 CHAR(64) NOT NULL,
 created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 content JSONB NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1,
 state VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','reviewed','handed_off')),
 reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
 reviewed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS study_workflows_org ON study_content_workflows(organization_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS study_content_workflow_posts (
 workflow_id UUID NOT NULL REFERENCES study_content_workflows(id) ON DELETE CASCADE,
 platform VARCHAR(16) NOT NULL CHECK (platform IN ('tiktok','instagram','youtube')),
 post_id UUID NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
 PRIMARY KEY (workflow_id, platform)
);
"""


async def init_study_workflow_schema(conn):
    await conn.execute(SQL)
