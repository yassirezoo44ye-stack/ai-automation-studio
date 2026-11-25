# Archived Alembic configuration

Archived 2026-11-15 (Flow audit, BE-04), by decision of the project owner.

Alembic was never how this app's schema reaches production. The revision
chain was broken past `001` (`alembic history` failed on
`003_ai_gateway.py`; `002` pointed at a non-existent `001_initial_schema`
revision; `003`–`014` use `up(conn)/down(conn)` shapes with no revision
metadata), and no deploy path (`Dockerfile`, `render.yaml`,
`railway.toml`) ever ran it.

**The schema source of truth is `app.factory.lifespan()`**: the idempotent
`init_db()` / `ensure_*_table()` / `init_*_schema()` calls it runs on every
startup. To change the schema, edit the relevant `init_*_schema()` function.

`migrations/versions/*.py` stay in place as SQL references (some are also
imported directly by `lifespan()` and by tests). `scripts/ci_schema_check.py`
fails CI if any table declared there is not created by `lifespan()`.

Do not restore these files and run `alembic upgrade head` against an
existing database: it would try to re-create tables `lifespan()` already
manages. Any future move to a real migration tool needs a baseline/stamp
plan, a backup and explicit approval first.
