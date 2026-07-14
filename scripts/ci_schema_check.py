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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if not os.getenv("DATABASE_URL"):
    print("DATABASE_URL must be set before running this check.", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    from app.factory import create_app, lifespan

    app = create_app()
    try:
        async with lifespan(app):
            print("SCHEMA CHECK PASSED: lifespan startup completed cleanly "
                  "against a fresh database.")
    except Exception as exc:
        print(f"SCHEMA CHECK FAILED: lifespan startup raised {exc!r}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
