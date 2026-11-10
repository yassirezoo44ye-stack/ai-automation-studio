"""Axon core schema (schema `axon`) — applies init_db.sql.

init_db.sql is the single source of truth for the Axon schema and is
idempotent, so this revision simply executes it. It lives in its own Alembic
environment (migrations_axon/, section [axon] of alembic.ini) because the
legacy migrations/ directory cannot be loaded by Alembic at all (003/004 have
no revision ids; see the note in 005_billing_platform.py):

    alembic -n axon upgrade head

After init_db.sql changes, add a revision here (down_revision = the previous
one) that executes the file again; it is safe to re-run.

Downgrade drops the whole `axon` schema and every tenant's data in it, so it
refuses to run unless AXON_ALLOW_SCHEMA_DROP=yes-drop-all-axon-data is set.

Revision ID: axon_0001
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import op

revision = "axon_0001"
down_revision = None
branch_labels = None
depends_on = None

_INIT_SQL = Path(__file__).resolve().parents[2] / "init_db.sql"
_DROP_CONFIRMATION = "yes-drop-all-axon-data"


def _script_body() -> str:
    """init_db.sql without its own BEGIN/COMMIT: Alembic owns the transaction."""
    lines = _INIT_SQL.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if ln.strip().upper() not in {"BEGIN;", "COMMIT;"}]
    return "\n".join(kept)


def upgrade() -> None:
    # Raw DB-API cursor with no parameters: the script contains '%' (format()
    # placeholders) that driver-level parameter interpolation would mangle.
    cursor = op.get_bind().connection.dbapi_connection.cursor()
    try:
        cursor.execute(_script_body())
    finally:
        cursor.close()


def downgrade() -> None:
    if os.environ.get("AXON_ALLOW_SCHEMA_DROP") != _DROP_CONFIRMATION:
        raise RuntimeError(
            "Refusing to drop schema axon (all Axon data). "
            f"Set AXON_ALLOW_SCHEMA_DROP={_DROP_CONFIRMATION} to confirm.",
        )
    op.execute("DROP SCHEMA IF EXISTS axon CASCADE")
