"""
Event bus API — Layer 2 (Core Services).

GET /api/events/stats     backend + subscription stats
GET /api/events/replay    replay history (filter by prefix / since)
GET /api/events/dlq       dead-letter entries
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.events import get_event_bus

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stats")
async def stats():
    return get_event_bus().stats()


@router.get("/replay")
async def replay(since_ts: float = 0.0, type_prefix: str = "", limit: int = 100):
    events = await get_event_bus().replay(
        since_ts=since_ts, type_prefix=type_prefix, limit=min(limit, 500),
    )
    return {"events": [e.to_dict() for e in events]}


@router.get("/dlq")
async def dead_letters(limit: int = 50):
    return {"dead_letters": get_event_bus().dead_letters(limit)}
