"""
Social Publisher — Schema Init Tests

Tests cover:
  S-1   _SCHEMA_SQL uses CREATE TABLE IF NOT EXISTS (idempotent)
  S-2   All three tables present in _SCHEMA_SQL
  S-3   All eight indexes present in _SCHEMA_SQL
  S-4   init_social_publisher_schema is exported from router
  S-5   init_social_publisher_schema is called in factory.py lifespan
  S-6   factory.py imports init_social_publisher_schema correctly
  S-7   Migration file 014 is valid Python syntax
  S-8   Migration 014 has SQL_UP, SQL_DOWN, up() and down()
  S-9   Migration 014 SQL_UP matches router _SCHEMA_SQL (structural parity)
  S-10  platform CHECK covers tiktok, instagram, youtube in all tables
  S-11  UNIQUE constraint on social_platform_accounts is present
  S-12  UNIQUE constraint on social_publish_jobs (post_id, platform)
  S-13  All FK references are present (organizations, users, social_posts)
  S-14  Token columns are encrypted (access_token_enc, refresh_token_enc)
  S-15  Router file is valid Python syntax after schema addition
  S-16  asyncpg.Connection type annotation on init_social_publisher_schema
  S-17  SQL_DOWN drops in dependency order (jobs → posts → accounts)
  S-18  Partial indexes use WHERE clause
  S-19  social_posts.status CHECK covers all 6 values
  S-20  social_publish_jobs.status CHECK covers all 5 values
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _parse(rel: str) -> ast.Module:
    return ast.parse(_read(rel))


# ── S-1  Idempotent DDL ───────────────────────────────────────────────────────

def test_schema_sql_uses_if_not_exists():
    src = _read("app/routers/social_publisher.py")
    count = src.count("CREATE TABLE IF NOT EXISTS")
    assert count == 3, (
        f"Expected 3 CREATE TABLE IF NOT EXISTS statements, found {count}"
    )


def test_schema_indexes_use_if_not_exists():
    src = _read("app/routers/social_publisher.py")
    count = src.count("CREATE INDEX IF NOT EXISTS")
    assert count == 8, (
        f"Expected 8 CREATE INDEX IF NOT EXISTS statements, found {count}"
    )


# ── S-2  All three tables present ────────────────────────────────────────────

@pytest.mark.parametrize("table", [
    "social_platform_accounts",
    "social_posts",
    "social_publish_jobs",
])
def test_table_in_schema_sql(table):
    src = _read("app/routers/social_publisher.py")
    assert table in src, f"_SCHEMA_SQL must define table: {table}"


# ── S-3  All eight indexes present ───────────────────────────────────────────

@pytest.mark.parametrize("idx", [
    "idx_spa_org_platform",
    "idx_spa_user",
    "idx_sp_org_status",
    "idx_sp_org_scheduled",
    "idx_sp_created",
    "idx_spj_org_status",
    "idx_spj_post",
    "idx_spj_queued",
])
def test_index_in_schema_sql(idx):
    src = _read("app/routers/social_publisher.py")
    assert idx in src, f"_SCHEMA_SQL must define index: {idx}"


# ── S-4  init_social_publisher_schema is exported from router ─────────────────

def test_init_schema_function_exists():
    from app.routers.social_publisher import init_social_publisher_schema
    assert callable(init_social_publisher_schema)


def test_init_schema_is_async():
    from app.routers.social_publisher import init_social_publisher_schema
    assert inspect.iscoroutinefunction(init_social_publisher_schema)


# ── S-5  init_social_publisher_schema called in factory.py ───────────────────

def test_factory_calls_init_social_publisher_schema():
    src = _read("app/factory.py")
    assert "init_social_publisher_schema" in src, (
        "factory.py lifespan must call init_social_publisher_schema"
    )
    assert "await init_social_publisher_schema(conn)" in src, (
        "factory.py must await init_social_publisher_schema(conn)"
    )


# ── S-6  factory.py imports from router ──────────────────────────────────────

def test_factory_imports_from_social_publisher():
    src = _read("app/factory.py")
    assert "from app.routers.social_publisher import init_social_publisher_schema" in src


# ── S-7  Migration file 014 is valid Python ───────────────────────────────────

def test_migration_014_is_valid_python():
    p = _ROOT / "migrations/versions/014_social_publisher.py"
    assert p.exists(), "migrations/versions/014_social_publisher.py not found"
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        pytest.fail(f"014_social_publisher.py has a syntax error: {e}")


# ── S-8  Migration 014 has required components ────────────────────────────────

def test_migration_014_has_sql_up_and_down():
    src = _read("migrations/versions/014_social_publisher.py")
    assert "SQL_UP" in src, "014 must define SQL_UP"
    assert "SQL_DOWN" in src, "014 must define SQL_DOWN"
    assert "def up" in src, "014 must define up()"
    assert "def down" in src, "014 must define down()"


# ── S-9  Structural parity: migration DDL and router _SCHEMA_SQL ──────────────

@pytest.mark.parametrize("table", [
    "social_platform_accounts",
    "social_posts",
    "social_publish_jobs",
])
def test_migration_014_and_router_define_same_tables(table):
    migration_src = _read("migrations/versions/014_social_publisher.py")
    router_src    = _read("app/routers/social_publisher.py")
    assert table in migration_src, f"Migration 014 SQL_UP must reference: {table}"
    assert table in router_src,    f"Router _SCHEMA_SQL must reference: {table}"


# ── S-10  Platform CHECK covers all three platforms ───────────────────────────

@pytest.mark.parametrize("platform", ["tiktok", "instagram", "youtube"])
def test_platform_check_constraint(platform):
    src = _read("app/routers/social_publisher.py")
    # Platform CHECK appears in social_platform_accounts and social_publish_jobs
    assert src.count(f"'{platform}'") >= 2, (
        f"Platform '{platform}' must appear in CHECK constraints for both tables"
    )


# ── S-11  UNIQUE constraint on social_platform_accounts ──────────────────────

def test_unique_constraint_on_platform_accounts():
    src = _read("app/routers/social_publisher.py")
    assert "organization_id, user_id, platform, platform_user_id" in src, (
        "social_platform_accounts must have UNIQUE(org, user, platform, platform_user_id)"
    )


# ── S-12  UNIQUE constraint on social_publish_jobs ────────────────────────────

def test_unique_constraint_prevents_double_dispatch():
    src = _read("app/routers/social_publisher.py")
    assert "UNIQUE (post_id, platform)" in src, (
        "social_publish_jobs must have UNIQUE(post_id, platform) to prevent double-dispatch"
    )


# ── S-13  FK references are present ──────────────────────────────────────────

@pytest.mark.parametrize("fk_ref", [
    "REFERENCES organizations(id)",
    "REFERENCES users(id)",
    "REFERENCES social_posts(id)",
    "REFERENCES social_platform_accounts(id)",
])
def test_foreign_keys_present(fk_ref):
    src = _read("app/routers/social_publisher.py")
    assert fk_ref in src, f"_SCHEMA_SQL must contain FK: {fk_ref}"


# ── S-14  Token columns use encrypted names ───────────────────────────────────

def test_token_columns_are_encrypted():
    src = _read("app/routers/social_publisher.py")
    assert "access_token_enc" in src, "Token column must be named access_token_enc (encrypted)"
    assert "refresh_token_enc" in src, "Token column must be named refresh_token_enc (encrypted)"
    # Ensure unencrypted names are NOT column definitions in schema
    schema_block_start = src.index("_SCHEMA_SQL")
    schema_block_end   = src.index('"""', src.index('_SCHEMA_SQL = """') + 12)
    schema_block = src[schema_block_start:schema_block_end + 3]
    assert "access_token " not in schema_block, \
        "Schema must not store access_token in plaintext — use access_token_enc"
    assert "refresh_token " not in schema_block, \
        "Schema must not store refresh_token in plaintext — use refresh_token_enc"


# ── S-15  Router file is valid Python after schema addition ───────────────────

def test_router_is_valid_python():
    try:
        _parse("app/routers/social_publisher.py")
    except SyntaxError as e:
        pytest.fail(f"social_publisher.py has a syntax error: {e}")


# ── S-16  Type annotation uses asyncpg.Connection ────────────────────────────

def test_init_schema_has_asyncpg_annotation():
    src = _read("app/routers/social_publisher.py")
    assert "asyncpg.Connection" in src, (
        "init_social_publisher_schema must annotate conn as asyncpg.Connection"
    )


# ── S-17  SQL_DOWN drops in dependency order ──────────────────────────────────

def test_sql_down_dependency_order():
    # jobs must be dropped before posts, posts before accounts
    # SQL_DOWN is in the migration file, not the router
    migration_src = _read("migrations/versions/014_social_publisher.py")
    jobs_pos     = migration_src.index("social_publish_jobs",
                                        migration_src.index("SQL_DOWN"))
    posts_pos    = migration_src.index("social_posts",
                                        migration_src.index("SQL_DOWN"))
    accounts_pos = migration_src.index("social_platform_accounts",
                                        migration_src.index("SQL_DOWN"))
    assert jobs_pos < posts_pos < accounts_pos, (
        "SQL_DOWN must drop: jobs → posts → accounts (FK dependency order)"
    )


# ── S-18  Partial indexes use WHERE clause ────────────────────────────────────

def test_partial_indexes_have_where():
    src = _read("app/routers/social_publisher.py")
    # idx_sp_org_scheduled and idx_spj_queued are partial
    assert "WHERE scheduled_at IS NOT NULL AND status = 'scheduled'" in src
    assert "WHERE status = 'queued'" in src


# ── S-19  social_posts.status CHECK values ────────────────────────────────────

@pytest.mark.parametrize("status_val", [
    "draft", "scheduled", "publishing", "published", "partial", "failed"
])
def test_social_posts_status_check_values(status_val):
    src = _read("app/routers/social_publisher.py")
    assert f"'{status_val}'" in src, (
        f"social_posts.status CHECK must include value: '{status_val}'"
    )


# ── S-20  social_publish_jobs.status CHECK values ────────────────────────────

@pytest.mark.parametrize("status_val", [
    "queued", "processing", "completed", "failed", "cancelled"
])
def test_social_publish_jobs_status_check_values(status_val):
    src = _read("app/routers/social_publisher.py")
    assert f"'{status_val}'" in src, (
        f"social_publish_jobs.status CHECK must include value: '{status_val}'"
    )
