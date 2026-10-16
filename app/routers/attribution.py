"""
Attribution API — minimal first-party funnel measurement.

POST /api/track   (no auth — anonymous)

Accepts: landing_visit | cta_click | signup
Stores UTM attribution + anonymous session_id.
No PII: session_id is a client-generated UUID, not tied to a user account.

Rate-limited 120/60s per IP to deter abuse without blocking legit page views.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.core.db import get_pool
from app.core.rate_limit import make_rate_limit_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["attribution"])

_ALLOWED_EVENTS = frozenset({"landing_visit", "cta_click", "signup"})

_rl = Depends(make_rate_limit_dep("attribution_track", max_calls=120, window=60))


class TrackRequest(BaseModel):
    event:        str            = Field(..., max_length=40)
    session_id:   str            = Field(..., min_length=1, max_length=64)
    utm_source:   Optional[str]  = Field(default=None, max_length=200)
    utm_medium:   Optional[str]  = Field(default=None, max_length=200)
    utm_campaign: Optional[str]  = Field(default=None, max_length=200)
    utm_content:  Optional[str]  = Field(default=None, max_length=200)

    @field_validator("event")
    @classmethod
    def validate_event(cls, v: str) -> str:
        if v not in _ALLOWED_EVENTS:
            from fastapi import HTTPException
            raise HTTPException(400, f"Unknown event '{v}'")
        return v


@router.post("/api/track", status_code=204)
async def track(
    body: TrackRequest,
    request: Request,
    _rl: None = _rl,
) -> None:
    """Record an anonymous attribution event. Never raises — silently drops on DB error."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO attribution_events
                    (event_name, session_id, utm_source, utm_medium, utm_campaign, utm_content)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                body.event,
                body.session_id,
                body.utm_source,
                body.utm_medium,
                body.utm_campaign,
                body.utm_content,
            )
    except Exception:
        log.debug("attribution track silently dropped", exc_info=True)
