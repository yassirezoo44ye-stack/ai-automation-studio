"""Flow Next — Interactions (Phase 2)

Adds flow_creation_interactions for like/save persistence.
NOTE: actual schema creation happens via startup _SCHEMA_SQL in
app/routers/discover.py (init_flow_creations_schema).  This file is for
versioning/documentation only and is not executed by a migration runner.
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS flow_creation_interactions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    creation_id     UUID        NOT NULL REFERENCES flow_creations(id) ON DELETE CASCADE,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type            VARCHAR(10) NOT NULL CHECK (type IN ('like', 'save')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (creation_id, user_id, type)
);
CREATE INDEX IF NOT EXISTS ix_fci_creation_type
    ON flow_creation_interactions(creation_id, type);
CREATE INDEX IF NOT EXISTS ix_fci_user_type
    ON flow_creation_interactions(user_id, type);
"""

SQL_DOWN = "DROP TABLE IF EXISTS flow_creation_interactions CASCADE;"


async def up(conn) -> None:
    await conn.execute(SQL_UP)


async def down(conn) -> None:
    await conn.execute(SQL_DOWN)
