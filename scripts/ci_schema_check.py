"""
CI schema-safety check.

The real production schema mechanism is NOT `alembic upgrade head` — the
Alembic revision chain is non-functional beyond migration 001 (migrations
002+ use a different, non-Alembic `up(conn)/down(conn)` shape with no
`revision`/`down_revision` metadata). Production has always relied on the
idempotent `init_db()` + `ensure_*_table()`/`init_*_schema()` calls that
`app.factory.lifespan()` runs on every startup.

This script exercises that exact mechanism — not a reimplementation of it —
by running the app's own `lifespan()` context manager against a fresh
database, proving the actual deploy-time schema path works end to end.
Requires DATABASE_URL to point at an empty database before any app module
is imported (app.core.config reads it once, at import time).
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if not os.getenv("DATABASE_URL"):
    print("DATABASE_URL must be set before running this check.", file=sys.stderr)
    sys.exit(1)


# Tables declared in migrations/versions/*.py that lifespan() intentionally
# does not create. 001's `agents` was superseded by `ai_agents`
# (app/core/db.py ensure_agents_table); no code reads `agents`.
_RETIRED_MIGRATION_TABLES = {"agents"}

_CREATE_TABLE_RE = re.compile(
    r"""create\s+table\s+(?:if\s+not\s+exists\s+)?"?([a-z_][a-z0-9_]*)"?\s*\(""",
    re.IGNORECASE,
)
_OP_CREATE_TABLE_RE = re.compile(r"""op\.create_table\(\s*["']([a-z_][a-z0-9_]*)["']""")


def _tables_declared_in_migrations() -> dict[str, str]:
    """table name -> first migration file that declares it."""
    declared: dict[str, str] = {}
    versions = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    for path in sorted(versions.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for rx in (_CREATE_TABLE_RE, _OP_CREATE_TABLE_RE):
            for name in rx.findall(src):
                declared.setdefault(name.lower(), path.name)
    return declared


async def _missing_migration_tables() -> list[str]:
    """Schema-parity guard (BE-04): production never runs Alembic, so every
    table a migration file declares must also be created by lifespan().
    A new migration added without a matching init_*_schema() call would
    otherwise ship a table that exists nowhere in production."""
    from app.core.db import get_pool

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        )
    live = {r["tablename"] for r in rows}
    return sorted(
        f"{table} (declared in {origin})"
        for table, origin in _tables_declared_in_migrations().items()
        if table not in live and table not in _RETIRED_MIGRATION_TABLES
    )


async def main() -> None:
    from app.factory import create_app, lifespan

    app = create_app()
    try:
        async with lifespan(app):
            missing = await _missing_migration_tables()
    except Exception as exc:
        print(f"SCHEMA CHECK FAILED: lifespan startup raised {exc!r}", file=sys.stderr)
        sys.exit(1)
    if missing:
        print("SCHEMA CHECK FAILED: tables declared in migrations/versions but "
              "not created by lifespan():\n  " + "\n  ".join(missing), file=sys.stderr)
        sys.exit(1)
    print("SCHEMA CHECK PASSED: lifespan startup completed cleanly against a "
          "fresh database, and every table declared in migrations/versions exists.")


if __name__ == "__main__":
    asyncio.run(main())
