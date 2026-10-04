"""
Lead Engine schema — idempotent DDL.

Follows automation_schema.py conventions:
  CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
  ALTER TABLE … ADD COLUMN IF NOT EXISTS for forward-compatible evolution
  No FK to organizations (org_id carried by every row, not a PG FK)
  PostgreSQL 14+, asyncpg-compatible parameterised SQL
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

_SQL_LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL,
    name            TEXT        NOT NULL,
    email           TEXT,
    phone           TEXT,
    source          TEXT,
    status          TEXT        NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new', 'qualified', 'contacted', 'won', 'lost')),
    ai_score        INTEGER,
    ai_notes        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_SQL_LEADS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_leads_org        ON leads(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_leads_org_status ON leads(organization_id, status)",
]


async def init_leads_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(_SQL_LEADS)
    for idx in _SQL_LEADS_INDEXES:
        await conn.execute(idx)
    log.info("leads schema ready")
