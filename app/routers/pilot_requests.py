"""
Paid-pilot requests from the public landing page.

POST /api/pilot-requests   (no auth — anonymous visitors)

Why this exists: the landing page's only paid offer is a founder-run pilot
(EXECUTION_BACKLOG.md #3/#6/#7). A visitor who wants one needs a contact
channel that reaches the founder without a sign-up, without an API key in
the browser, and without SMTP being configured.

Where a request goes:
  * a lead in the organisation named by PILOT_LEADS_ORG_ID (source
    "landing_pilot"), so it shows up on the founder's Leads page;
  * an in-app notification to every member of that organisation, carrying
    what the visitor wrote (notifications are per-user and access-checked,
    unlike lead listings, which is why the free text is kept off the lead);
  * an email to those members too, when SMTP_HOST is configured.

PILOT_LEADS_ORG_ID unset → 503, so the page can show its fallback instead
of pretending the request was received.

Abuse controls: 5 requests per IP per hour, a hidden "website" honeypot
field (filled → accepted silently and dropped), strict field lengths.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.rate_limit import make_rate_limit_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["pilot"])

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

_rl = Depends(make_rate_limit_dep(
    "pilot_request", max_calls=5, window=3600,
    error_detail="Too many requests from this network. Please try again later.",
))


def _one_line(value: str) -> str:
    return " ".join(value.split())


class PilotRequest(BaseModel):
    name:      str        = Field(..., min_length=1, max_length=120)
    email:     str        = Field(..., min_length=3, max_length=254)
    company:   str        = Field(..., min_length=1, max_length=120)
    team_size: Literal["1", "2-5", "6-20", "20+"] | None = None
    task:      str        = Field(..., min_length=10, max_length=1000)
    lang:      Literal["en", "ar"] = "en"
    # Honeypot: hidden from people, filled by naive bots.
    website:   str | None = Field(default=None, max_length=200)

    @field_validator("name", "company")
    @classmethod
    def _clean_line(cls, v: str) -> str:
        v = _one_line(v)
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("must be a valid email address")
        return v

    @field_validator("task")
    @classmethod
    def _clean_task(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("please describe the task in a sentence or two")
        return v


def pilot_org_id() -> str | None:
    """The organisation that receives pilot requests, or None when unset or invalid."""
    raw = (os.getenv("PILOT_LEADS_ORG_ID") or "").strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        log.error("PILOT_LEADS_ORG_ID is not a UUID; pilot requests are disabled")
        return None


@router.post("/api/pilot-requests", status_code=202)
async def create_pilot_request(body: PilotRequest, _rl: None = _rl) -> dict:
    """Record one pilot request. Returns only {"status": "received"}."""
    if body.website:
        log.info("pilot request dropped by honeypot")
        return {"status": "received"}

    org_id = pilot_org_id()
    if org_id is None:
        log.error("pilot request rejected: PILOT_LEADS_ORG_ID is not configured")
        raise HTTPException(503, "Pilot requests are not open right now.")

    from app.core.leads import get_lead_service

    try:
        lead = await get_lead_service().create(
            org_id=org_id,
            name=body.name,
            email=body.email,
            source="landing_pilot",
        )
    except Exception:
        log.exception("pilot request could not be stored")
        raise HTTPException(503, "We could not record your request. Please try again shortly.") from None

    await _notify_members(org_id=org_id, lead_id=str(lead.get("id")), body=body)
    log.info("pilot request stored lead_id=%s", lead.get("id"))
    return {"status": "received"}


def _summary(body: PilotRequest) -> str:
    size = f", team {body.team_size}" if body.team_size else ""
    return f"{body.name} <{body.email}> at {body.company}{size} ({body.lang}). Wants automated: {body.task}"


async def _notify_members(*, org_id: str, lead_id: str, body: PilotRequest) -> None:
    """In-app notification to every member, plus email when SMTP is set.
    Never raises: the request is already stored as a lead."""
    title = f"Pilot request: {body.company}"[:200]
    message = _summary(body)
    member_ids: list[str] = []
    try:
        from app.core.notifications.service import get_notification_service
        from app.routers.ws import manager as ws_manager
        svc = get_notification_service()
        member_ids = await svc.org_member_ids(organization_id=org_id)
        for user_id in member_ids:
            notification = await svc.create(
                user_id=user_id,
                organization_id=org_id,
                type_="lead.pilot_request",
                category="workflow",
                severity="success",
                title=title,
                message=message,
                source="landing_pilot",
                action={"label": "View leads", "href": "/leads"},
                dismissible=True,
            )
            await ws_manager.broadcast(f"notifications:{user_id}", notification)
    except Exception as exc:  # noqa: BLE001 — best effort; the lead is already stored
        log.warning("pilot request in-app notification failed lead_id=%s: %s", lead_id, exc)

    if not os.getenv("SMTP_HOST"):
        return
    try:
        from app.core.db import get_pool
        from app.core.email import send_email
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.email FROM users u
                JOIN organization_members om ON om.user_id = u.id
                WHERE om.organization_id = $1 AND om.deleted_at IS NULL
                  AND u.email IS NOT NULL
                """,
                uuid.UUID(org_id),
            )
        html = (
            f"<p><strong>{escape(body.name)}</strong> ({escape(body.email)}) from "
            f"<strong>{escape(body.company)}</strong> asked for a Flow pilot.</p>"
            f"<p><strong>Team size:</strong> {escape(body.team_size or '-')}<br>"
            f"<strong>Language:</strong> {escape(body.lang)}</p>"
            f"<p><strong>What they want automated:</strong><br>{escape(body.task)}</p>"
        )
        for row in rows:
            try:
                await send_email(row["email"], title, html)
            except Exception as exc:  # noqa: BLE001 — one bad address must not stop the rest
                log.warning("pilot request email failed lead_id=%s: %s", lead_id, exc)
    except Exception as exc:  # noqa: BLE001 — best effort; the lead is already stored
        log.warning("pilot request email dispatch failed lead_id=%s: %s", lead_id, exc)
