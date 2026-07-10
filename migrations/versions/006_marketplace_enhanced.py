"""
Production Marketplace — dependency resolution, versioning metadata,
publisher identity, security/asset infrastructure, org-visibility model.

Adds:
  marketplace_categories, marketplace_publishers, marketplace_dependencies,
  marketplace_assets, marketplace_changelog, marketplace_downloads

Also adds columns to the 4 pre-existing marketplace tables:
  marketplace_items.visibility/owner_organization_id/created_by/publisher_id
  marketplace_installs.uninstalled_at

Matches 005's up(conn)/down(conn) convention (not real Alembic — the
upstream 001-004 revision chain is already broken, out of this phase's
scope to repair; see 005's docstring). down() drops only the 6 new tables
plus the new columns; it does not touch marketplace_items/versions/
reviews/installs themselves (pre-existing, not introduced by this revision).
"""

SQL_UP = """
ALTER TABLE marketplace_items ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'public'
    CHECK (visibility IN ('public','private','internal'));
ALTER TABLE marketplace_items ADD COLUMN IF NOT EXISTS owner_organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE marketplace_items ADD COLUMN IF NOT EXISTS created_by UUID;
ALTER TABLE marketplace_installs ADD COLUMN IF NOT EXISTS uninstalled_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS marketplace_categories (
    slug        VARCHAR(30) PRIMARY KEY,
    label       VARCHAR(60) NOT NULL,
    icon        VARCHAR(10),
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO marketplace_categories (slug, label, icon, description, sort_order) VALUES
('agent',       'AI Agents',    '🤖', 'Autonomous agents for specialized tasks.', 0),
('plugin',      'Plugins',      '🧩', 'Extensions that add new capabilities.', 1),
('workflow',    'Workflows',    '🔀', 'Pre-built automation pipelines.', 2),
('prompt_pack', 'Prompt Packs', '📝', 'Curated prompt collections.', 3),
('theme',       'Themes',       '🎨', 'UI themes and visual styles.', 4),
('template',    'Templates',    '📄', 'Reusable project templates.', 5),
('dataset',     'Datasets',     '📊', 'Structured data for training and testing.', 6),
('model',       'Models',       '🧠', 'Fine-tuned or custom model configurations.', 7)
ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS marketplace_publishers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE UNIQUE,
    display_name      VARCHAR(120) NOT NULL,
    verified          BOOLEAN NOT NULL DEFAULT false,
    verified_at       TIMESTAMPTZ,
    verified_by       UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE marketplace_items ADD COLUMN IF NOT EXISTS publisher_id UUID REFERENCES marketplace_publishers(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS marketplace_dependencies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id             TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    depends_on_item_id  TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version_constraint  VARCHAR(30) NOT NULL DEFAULT '*',
    optional            BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id, depends_on_item_id),
    CHECK (item_id != depends_on_item_id)
);
CREATE INDEX IF NOT EXISTS idx_mkt_deps_item ON marketplace_dependencies(item_id);

CREATE TABLE IF NOT EXISTS marketplace_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version         VARCHAR(30) NOT NULL,
    asset_type      VARCHAR(30) NOT NULL DEFAULT 'inline',
    content         TEXT,
    external_url    TEXT,
    checksum_sha256 TEXT NOT NULL,
    size_bytes      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((asset_type = 'inline' AND content IS NOT NULL) OR (asset_type = 'url' AND external_url IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_mkt_assets_item ON marketplace_assets(item_id, version);

CREATE TABLE IF NOT EXISTS marketplace_changelog (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id  UUID NOT NULL REFERENCES marketplace_versions(id) ON DELETE CASCADE,
    change_type VARCHAR(20) NOT NULL CHECK (change_type IN ('added','changed','fixed','removed','security')),
    description TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mkt_changelog_version ON marketplace_changelog(version_id);

CREATE TABLE IF NOT EXISTS marketplace_downloads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id         TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    version         VARCHAR(30),
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    user_id         UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mkt_downloads_item ON marketplace_downloads(item_id, created_at DESC);
"""

SQL_DOWN = """
ALTER TABLE marketplace_items DROP COLUMN IF EXISTS publisher_id;
ALTER TABLE marketplace_items DROP COLUMN IF EXISTS visibility;
ALTER TABLE marketplace_items DROP COLUMN IF EXISTS owner_organization_id;
ALTER TABLE marketplace_items DROP COLUMN IF EXISTS created_by;
ALTER TABLE marketplace_installs DROP COLUMN IF EXISTS uninstalled_at;

DROP TABLE IF EXISTS marketplace_downloads;
DROP TABLE IF EXISTS marketplace_changelog;
DROP TABLE IF EXISTS marketplace_assets;
DROP TABLE IF EXISTS marketplace_dependencies;
DROP TABLE IF EXISTS marketplace_publishers;
DROP TABLE IF EXISTS marketplace_categories;
"""
# Deliberately does NOT touch marketplace_items/marketplace_versions/
# marketplace_reviews/marketplace_installs themselves (pre-existing tables,
# not introduced by this revision) — only the columns this revision added.


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
