"""
Event bus API — Layer 2 (Core Services).

GET /api/events/stats     backend + subscription stats
GET /api/events/replay    replay history (filter by prefix / since)
GET /api/events/dlq       dead-letter entries

Tenant boundary (P0.5 security fix, see docs/security-tenant-boundary-audit.md):
Event.organization_id is set on org-scoped event types (billing.*,
organization.*, integration.*, ...). replay()/dead_letters() previously
returned every org's history to any authenticated caller. Both now require
org_context and filter to the caller's own org_id; events published with no
organization_id (system-internal, not tenant data) are excluded rather than
shown to everyone, per deny-by-default. stats() is unchanged — it only
returns aggregate counts, no event content, so it carries no tenant data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.events import get_event_bus
from app.tenancy.context import OrgContext, org_context

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stats")
async def stats():
    return get_event_bus().stats()


@router.get("/replay")
async def replay(
    since_ts: float = 0.0, type_prefix: str = "", limit: int = 100,
    ctx: OrgContext = Depends(org_context),
):
    events = await get_event_bus().replay(
        since_ts=since_ts, type_prefix=type_prefix, limit=min(limit, 500),
    )
    return {"events": [e.to_dict() for e in events if e.organization_id == ctx.org_id]}


@router.get("/dlq")
async def dead_letters(limit: int = 50, ctx: OrgContext = Depends(org_context)):
    entries = get_event_bus().dead_letters(limit)
    return {
        "dead_letters": [
            e for e in entries if (e.get("event") or {}).get("organization_id") == ctx.org_id
        ],
    }
