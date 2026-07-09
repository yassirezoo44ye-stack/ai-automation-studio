"""
billing_events — raw Stripe webhook receipt log + delivery deduplication.

Doubles as the platform's "webhooks" audit entity: one row per Stripe event
id, so a replayed delivery (Stripe's guarantee is at-least-once, never
exactly-once) is detected before any side-effecting handler runs.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

BILLING_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS billing_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_event_id  TEXT UNIQUE NOT NULL,
    event_type       VARCHAR(80) NOT NULL,
    organization_id  UUID REFERENCES organizations(id) ON DELETE SET NULL,
    payload          JSONB NOT NULL,
    processed_at     TIMESTAMPTZ,
    error            TEXT,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_events_org  ON billing_events(organization_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_events_type ON billing_events(event_type, received_at DESC);
"""


async def init_billing_events_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(BILLING_EVENTS_SCHEMA)
    log.info("billing_events schema initialised")


class WebhookEventService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record(
        self, *, stripe_event_id: str, event_type: str, payload: dict[str, Any],
        organization_id: Optional[str] = None,
    ) -> bool:
        """Insert the raw event receipt, or detect a replayed delivery.

        Returns True if the caller should process this event now — either
        because it's genuinely new, or because a PRIOR delivery of this
        exact event id failed or never finished (so this delivery is a
        legitimate Stripe retry that must actually run, not be silently
        swallowed as a duplicate). Returns False only when a prior
        delivery of this event id fully succeeded (processed_at set, no
        error) — a true duplicate.
        """
        import uuid as _uuid
        org_uuid = _uuid.UUID(organization_id) if organization_id else None
        payload_json = json.dumps(payload, default=str)

        row = await self._pool.fetchrow(
            """INSERT INTO billing_events (stripe_event_id, event_type, organization_id, payload)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (stripe_event_id) DO NOTHING
               RETURNING id""",
            stripe_event_id, event_type, org_uuid, payload_json,
        )
        if row is not None:
            return True  # genuinely new event

        existing = await self._pool.fetchrow(
            "SELECT processed_at, error FROM billing_events WHERE stripe_event_id=$1",
            stripe_event_id,
        )
        if existing is None or existing["processed_at"] is None or existing["error"] is not None:
            # Never completed, or failed last time — treat this delivery as
            # a retry opportunity rather than swallowing it.
            await self._pool.execute(
                "UPDATE billing_events SET error=NULL, payload=$2 WHERE stripe_event_id=$1",
                stripe_event_id, payload_json,
            )
            return True
        return False  # already fully succeeded — true duplicate

    async def mark_processed(self, stripe_event_id: str) -> None:
        try:
            await self._pool.execute(
                "UPDATE billing_events SET processed_at=NOW(), error=NULL WHERE stripe_event_id=$1",
                stripe_event_id,
            )
        except Exception:
            log.debug("billing_events mark_processed failed", exc_info=True)

    async def mark_failed(self, stripe_event_id: str, error: str) -> None:
        """Leaves processed_at unset so a legitimate Stripe retry of this
        event id is treated as unfinished work, not a duplicate."""
        try:
            await self._pool.execute(
                "UPDATE billing_events SET processed_at=NULL, error=$2 WHERE stripe_event_id=$1",
                stripe_event_id, error[:2000],
            )
        except Exception:
            log.debug("billing_events mark_failed failed", exc_info=True)

    async def set_organization(self, stripe_event_id: str, organization_id: str) -> None:
        """Best-effort backfill once an event's org becomes resolvable."""
        try:
            import uuid as _uuid
            await self._pool.execute(
                "UPDATE billing_events SET organization_id=$2 WHERE stripe_event_id=$1",
                stripe_event_id, _uuid.UUID(organization_id),
            )
        except Exception:
            log.debug("billing_events set_organization failed", exc_info=True)


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[WebhookEventService] = None


def get_webhook_event_service(pool: asyncpg.Pool | None = None) -> WebhookEventService:
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = WebhookEventService(pool)
    return _service
