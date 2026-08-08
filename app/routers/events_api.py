"""
Event bus API — Layer 2 (Core Services).

GET /api/events/stats     backend + subscription stats
GET /api/events/replay    replay history (filter by prefix / since)
GET /api/events/dlq       dead-letter entries

SECURITY FIX: /replay and /dlq previously had no per-route auth beyond
api_auth_middleware's "/api/ requires *some* valid token" gate. Every
Event carries its own organization_id, but the bus returned every org's
history/dead-letters to any authenticated caller with no filtering —
workflow runs, job completions, marketplace activity, etc. from every
tenant, leaked to any signed-up user. Both endpoints now require
org_context (real, verified org membership, same as jobs_api.py) and
scope through EventBus.replay()/dead_letters()'s new org_id parameter.
/stats is left as-is — a platform-wide operational metric, not per-tenant
data.
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
        org_id=ctx.org_id,
    )
    return {"events": [e.to_dict() for e in events]}


@router.get("/dlq")
async def dead_letters(limit: int = 50, ctx: OrgContext = Depends(org_context)):
    return {"dead_letters": get_event_bus().dead_letters(limit, org_id=ctx.org_id)}
