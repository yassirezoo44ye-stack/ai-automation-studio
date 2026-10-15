"""
Attribution schema — idempotent DDL.

Stores anonymous funnel events (landing_visit, cta_click, signup) with UTM
attribution. No PII: session_id is a client-generated anonymous UUID.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

_SQL = """
CREATE TABLE IF NOT EXISTS attribution_events (
    id           BIGSERIAL    PRIMARY KEY,
    event_name   TEXT         NOT NULL
                 CHECK (event_name IN ('landing_visit', 'cta_click', 'signup')),
    session_id   TEXT         NOT NULL,
    utm_source   TEXT,
    utm_medium   TEXT,
    utm_campaign TEXT,
    utm_content  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
"""

_SQL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_attr_session    ON attribution_events(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_attr_created    ON attribution_events(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_attr_event_date ON attribution_events(event_name, created_at)",
]


async def init_attribution_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(_SQL)
    for idx in _SQL_INDEXES:
        await conn.execute(idx)
    log.info("attribution schema ready")
