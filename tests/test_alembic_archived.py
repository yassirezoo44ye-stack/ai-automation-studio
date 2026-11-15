"""BE-04 guard: Alembic is archived; lifespan() owns the schema.

A root-level alembic.ini would let `alembic upgrade head` run against a
database whose tables lifespan() already manages. See
migrations/_alembic_archive/README.md.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_no_active_alembic_config():
    assert not (_ROOT / "alembic.ini").exists()
    assert not (_ROOT / "migrations" / "env.py").exists()


def test_archive_explains_the_schema_source_of_truth():
    readme = (_ROOT / "migrations" / "_alembic_archive" / "README.md").read_text(encoding="utf-8")
    assert "lifespan()" in readme
