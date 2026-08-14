"""
Database typed tool executors — read-only schema inspection.

These tools use the application's OWN database pool (not an external provider).
They NEVER expose:
  - raw data rows (only schema metadata)
  - credentials
  - sensitive column values

Useful for Claude to understand the data model when debugging or planning
a migration — not for reading user data.
"""
from __future__ import annotations

import logging
from typing import Any

from app.engineering.tools.gateway import ToolDefinition, RiskLevel, get_tool_registry
from app.integrations.types import IntegrationCredential

log = logging.getLogger(__name__)


async def database_inspect_schema(
    credential: IntegrationCredential,  # unused — uses app pool directly
    args: dict[str, Any],
    org_id: str,
) -> dict:
    """Return table names and column metadata from the public schema.

    Returns structural information only — never row data.
    """
    from app.core.db import get_pool
    pool = get_pool()
    filter_table = args.get("table")
    async with pool.acquire() as conn:
        if filter_table:
            rows = await conn.fetch(
                """SELECT column_name, data_type, is_nullable, column_default
                   FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=$1
                   ORDER BY ordinal_position""",
                filter_table,
            )
            return {
                "table":   filter_table,
                "columns": [dict(r) for r in rows],
            }
        else:
            rows = await conn.fetch(
                """SELECT table_name, (
                       SELECT count(*) FROM information_schema.columns c2
                       WHERE c2.table_schema='public' AND c2.table_name=t.table_name
                   ) AS column_count
                   FROM information_schema.tables t
                   WHERE table_schema='public' AND table_type='BASE TABLE'
                   ORDER BY table_name""",
            )
            return {
                "tables": [{"name": r["table_name"], "column_count": r["column_count"]} for r in rows],
                "count":  len(rows),
            }


async def database_list_migrations(
    credential: IntegrationCredential,
    args: dict[str, Any],
    org_id: str,
) -> dict:
    """List applied Alembic migrations from alembic_version table."""
    from app.core.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("SELECT version_num FROM alembic_version ORDER BY version_num")
            return {"applied": [r["version_num"] for r in rows]}
        except Exception as exc:
            return {"error": str(exc), "applied": []}


_TOOL_FNS = {
    "database.inspect_schema":    database_inspect_schema,
    "database.list_migrations":   database_list_migrations,
}

DATABASE_TOOLS: dict[str, ToolDefinition] = {
    "database.inspect_schema": ToolDefinition(
        name="database.inspect_schema",
        provider="internal",
        operation="inspect_schema",
        description="Read table names and column metadata (no row data) from the application database",
        risk_level=RiskLevel.ANALYZE,
        required_args=[],
    ),
    "database.list_migrations": ToolDefinition(
        name="database.list_migrations",
        provider="internal",
        operation="list_migrations",
        description="List applied Alembic database migrations",
        risk_level=RiskLevel.ANALYZE,
        required_args=[],
    ),
}


def _register_database_tools() -> None:
    registry = get_tool_registry()
    for defn in DATABASE_TOOLS.values():
        registry.register(defn)
    from app.engineering.tools.gateway import ALL_TOOLS
    for name, fn in _TOOL_FNS.items():
        ALL_TOOLS[name] = fn


_register_database_tools()
