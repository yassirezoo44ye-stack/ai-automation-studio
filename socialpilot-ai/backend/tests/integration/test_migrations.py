"""Migrations must apply and roll back cleanly from a blank database.

Runs against a scratch database (created and dropped per test) rather than the
shared `socialpilot_test` database, since it tears the schema down entirely —
running it against the shared DB would race with every other test in the suite.
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
PG_ADMIN_URL = "postgresql://postgres:postgres@localhost:5432/postgres"


def _psql(sql: str) -> None:
    subprocess.run(
        ["psql", PG_ADMIN_URL, "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )


def _alembic(*args: str, db_name: str) -> subprocess.CompletedProcess:
    url = f"postgresql+asyncpg://postgres:postgres@localhost:5432/{db_name}"
    return subprocess.run(
        ["./.venv/bin/alembic", "-x", f"db_url={url}", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch_db() -> str:
    db_name = f"socialpilot_migtest_{uuid.uuid4().hex[:10]}"
    _psql(f'CREATE DATABASE "{db_name}"')
    try:
        yield db_name
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')


def test_upgrade_head_succeeds_from_blank_database(scratch_db: str) -> None:
    result = _alembic("upgrade", "head", db_name=scratch_db)
    assert result.returncode == 0, result.stderr


def test_downgrade_base_then_upgrade_head_round_trips(scratch_db: str) -> None:
    up1 = _alembic("upgrade", "head", db_name=scratch_db)
    assert up1.returncode == 0, up1.stderr

    down = _alembic("downgrade", "base", db_name=scratch_db)
    assert down.returncode == 0, down.stderr

    up2 = _alembic("upgrade", "head", db_name=scratch_db)
    assert up2.returncode == 0, up2.stderr
