"""The Axon Alembic environment (alembic -n axon) applies init_db.sql and refuses unconfirmed drops."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

ADMIN_URL = os.getenv("AXON_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="AXON_TEST_DATABASE_URL not set")


@pytest.fixture
def blank_db():
    import psycopg2
    from sqlalchemy.engine import make_url

    name = f"axon_mig_{uuid.uuid4().hex[:10]}"
    admin = make_url(ADMIN_URL)
    dsn = admin.set(drivername="postgresql").render_as_string(hide_password=False)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    conn.cursor().execute(f'CREATE DATABASE "{name}"')
    try:
        yield admin.set(drivername="postgresql", database=name).render_as_string(hide_password=False)
    finally:
        conn.cursor().execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.close()


def _alembic(url: str, monkeypatch):
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"), ini_section="axon")
    cfg.set_main_option("script_location", str(ROOT / "migrations_axon"))
    return cfg


def _axon_tables(url: str) -> set[str]:
    import psycopg2

    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'axon'")
        return {r[0] for r in cur.fetchall()}


def test_upgrade_downgrade_upgrade(blank_db, monkeypatch):
    from alembic import command

    cfg = _alembic(blank_db, monkeypatch)
    command.upgrade(cfg, "head")
    assert {"organizations", "users", "api_keys", "refresh_tokens", "audit_events"} <= _axon_tables(blank_db)

    monkeypatch.delenv("AXON_ALLOW_SCHEMA_DROP", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to drop"):
        command.downgrade(cfg, "base")
    assert "users" in _axon_tables(blank_db)

    monkeypatch.setenv("AXON_ALLOW_SCHEMA_DROP", "yes-drop-all-axon-data")
    command.downgrade(cfg, "base")
    assert _axon_tables(blank_db) == set()

    command.upgrade(cfg, "head")
    assert "refresh_tokens" in _axon_tables(blank_db)
