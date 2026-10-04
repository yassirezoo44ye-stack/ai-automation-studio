"""
Lead Engine REST API.

GET    /api/leads                 list org's leads (paginated)
POST   /api/leads                 create a lead + trigger AI qualification
GET    /api/leads/{id}            get one lead
PATCH  /api/leads/{id}/status     update lead status
POST   /api/leads/{id}/qualify    re-run AI qualification

Security:
  • Every endpoint requires a verified OrgContext.
  • Read endpoints: leads:read permission.
  • Write/mutate endpoints: leads:write permission.
  • All queries filter by organization_id — no IDOR possible.
  • 404 (not 403) for missing/other-org leads so callers cannot enumerate.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.leads import get_lead_service
from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _not_found() -> HTTPException:
    return HTTPException(404, "Lead not found")


# ── Request models ────────────────────────────────────────────────────────────

class CreateLeadRequest(BaseModel):
    name:   str           = Field(..., min_length=1, max_length=200)
    email:  Optional[str] = Field(default=None, max_length=320)
    phone:  Optional[str] = Field(default=None, max_length=30)
    source: Optional[str] = Field(default=None, max_length=100)


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(new|qualified|contacted|won|lost)$")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_leads(
    status: Optional[str] = None,
    before: Optional[str] = None,
    limit: int = 50,
    ctx: OrgContext = Depends(require_permission("leads", "read")),
):
    if status and status not in ("new", "qualified", "contacted", "won", "lost"):
        raise HTTPException(400, f"Invalid status {status!r}")
    items = await get_lead_service().list(
        org_id=ctx.org_id, status=status, before=before, limit=limit,
    )
    return {"leads": items, "has_more": len(items) == max(1, min(limit, 200))}


@router.post("", status_code=201)
async def create_lead(
    body: CreateLeadRequest,
    ctx: OrgContext = Depends(require_permission("leads", "write")),
):
    svc = get_lead_service()
    lead = await svc.create(
        org_id=ctx.org_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        source=body.source,
    )
    lead_id = lead["id"]

    qualified_lead = await svc.qualify(lead_id=lead_id, org_id=ctx.org_id)

    follow_up_status = "no_definition"
    try:
        from app.core.db import get_pool
        from app.core.jobs import get_job_queue
        import uuid as _uuid
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM automation_definitions
                WHERE organization_id = $1
                  AND deleted_at IS NULL
                  AND definition->>'lead_followup' = 'true'
                LIMIT 1
                """,
                _uuid.UUID(ctx.org_id),
            )
        if row:
            run_id = str(_uuid.uuid4())
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO automation_runs
                        (organization_id, definition_id, run_id, name, status,
                         context, triggered_by, triggered_by_user)
                    VALUES ($1,$2,$3,$4,'pending',$5::jsonb,'lead_engine',$6)
                    """,
                    _uuid.UUID(ctx.org_id),
                    row["id"],
                    run_id,
                    "lead-followup",
                    f'{{"lead_id":"{lead_id}"}}',
                    _uuid.UUID(ctx.user_id),
                )
            await get_job_queue().submit(
                "automation.trigger.manual",
                payload={"definition_id": str(row["id"]), "context": {"lead_id": lead_id}},
                org_id=ctx.org_id,
                idempotency_key=run_id,
            )
            follow_up_status = "enqueued"
    except Exception as exc:
        log.warning("lead follow-up enqueue failed lead_id=%s: %s", lead_id, exc)

    if qualified_lead.get("status") == "qualified":
        await svc.dispatch_qualified_notification(lead=qualified_lead, org_id=ctx.org_id)

    return {**qualified_lead, "follow_up_status": follow_up_status}


@router.get("/{lead_id}")
async def get_lead(
    lead_id: str,
    ctx: OrgContext = Depends(require_permission("leads", "read")),
):
    lead = await get_lead_service().get(lead_id=lead_id, org_id=ctx.org_id)
    if lead is None:
        raise _not_found()
    return lead


@router.patch("/{lead_id}/status")
async def update_status(
    lead_id: str,
    body: UpdateStatusRequest,
    ctx: OrgContext = Depends(require_permission("leads", "write")),
):
    lead = await get_lead_service().update_status(
        lead_id=lead_id, org_id=ctx.org_id, status=body.status,
    )
    if lead is None:
        raise _not_found()
    return lead


@router.post("/{lead_id}/qualify")
async def requalify_lead(
    lead_id: str,
    ctx: OrgContext = Depends(require_permission("leads", "write")),
):
    svc = get_lead_service()
    existing = await svc.get(lead_id=lead_id, org_id=ctx.org_id)
    if existing is None:
        raise _not_found()
    lead = await svc.qualify(lead_id=lead_id, org_id=ctx.org_id)
    if lead.get("status") == "qualified":
        await svc.dispatch_qualified_notification(lead=lead, org_id=ctx.org_id)
    return lead
