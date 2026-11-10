"""Alembic environment for the Axon core schema (``alembic -n axon ...``).

Reads DATABASE_URL from the environment so credentials never live in
alembic.ini. Versions are tracked in axon_alembic_version (public schema),
separate from the legacy migrations' alembic_version table.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

VERSION_TABLE = "axon_alembic_version"


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, version_table=VERSION_TABLE,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, version_table=VERSION_TABLE, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
