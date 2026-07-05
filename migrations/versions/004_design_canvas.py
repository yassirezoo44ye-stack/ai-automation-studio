"""
Design canvas persistence.

Adds:
  design_canvases — stores Fabric.js canvas JSON per project, keyed by design_id
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS design_canvases (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID        NOT NULL,
    name        TEXT        NOT NULL DEFAULT 'Untitled Design',
    canvas_json JSONB       NOT NULL DEFAULT '{}',
    thumbnail   TEXT,
    width       INTEGER     NOT NULL DEFAULT 1080,
    height      INTEGER     NOT NULL DEFAULT 1080,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dc_project_idx ON design_canvases(project_id);
CREATE INDEX IF NOT EXISTS dc_updated_idx ON design_canvases(updated_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS design_canvases;
"""


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
