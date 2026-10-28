"""
Lead Engine REST API.

GET    /api/leads                 list org's leads (paginated)
POST   /api/leads                 create a lead + trigger AI qualification
POST   /api/leads/capture         external lead capture — API key auth, no JWT
GET    /api/leads/{id}            get one lead
PATCH  /api/leads/{id}/status     update lead status
POST   /api/leads/{id}/qualify    re-run AI qualification
POST   /api/leads/{id}/ai-followup  AI follow-up email draft (never sent)
POST   /api/leads/brief           AI pipeline brief (counts + next actions)

Security:
  • Authenticated endpoints require a verified OrgContext (JWT + org membership).
  • Read endpoints: leads:read permission.
  • Write/mutate endpoints: leads:write permission.
  • /capture uses an org-scoped API key (X-API-Key header) — no JWT required.
    The org is derived from the API key credential, never from the request body.
  • All queries filter by organization_id — no IDOR possible.
  • 404 (not 403) for missing/other-org leads so callers cannot enumerate.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field

from app.core.leads import get_lead_service
from app.core.leads.ai import LeadAIError
from app.core.api_keys import require_api_key, ApiKeyRecord
from app.core.rate_limit import make_rate_limit_dep
from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])


async def _enqueue_lead_followup(
    *, org_id: str, lead_id: str, triggered_by: str, user_id: str | None,
) -> str:
    """Start the org's lead follow-up automation for one lead, if one exists.

    Returns the follow_up_status reported to the caller:
      "no_definition"  — the org has no active lead_followup automation
      "enqueued"       — a pending run was recorded and its job submitted
      "failed"         — the run could not be started; if its row was
                         already written it is marked failed, never left
                         'pending' forever
    """
    import json
    import uuid as _uuid
    from app.core.db import get_pool
    from app.core.jobs import get_job_queue

    run_id: str | None = None
    pool = None
    try:
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
                _uuid.UUID(org_id),
            )
        if not row:
            return "no_definition"
        run_id = str(_uuid.uuid4())
        context = {"lead_id": lead_id}
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO automation_runs
                    (organization_id, definition_id, run_id, name, status,
                     context, triggered_by, triggered_by_user)
                VALUES ($1,$2,$3,$4,'pending',$5::jsonb,$6,$7)
                """,
                _uuid.UUID(org_id),
                row["id"],
                run_id,
                "lead-followup",
                json.dumps(context),
                triggered_by,
                _uuid.UUID(user_id) if user_id else None,
            )
        await get_job_queue().submit(
            "automation.trigger.manual",
            payload={
                "definition_id": str(row["id"]),
                "run_id": run_id,
                "context": context,
                "triggered_by": triggered_by,
                "triggered_by_user": user_id,
            },
            org_id=org_id,
            # Tie dedup to the lead, not the run UUID, so concurrent duplicate
            # requests (same lead_id + org) produce only one follow-up job.
            idempotency_key=f"lead-followup:{org_id}:{lead_id}",
        )
        return "enqueued"
    except Exception as exc:
        log.warning("lead follow-up enqueue failed lead_id=%s: %s", lead_id, exc)
        if run_id and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE automation_runs SET status='failed', error=$2, finished_at=now() "
                        "WHERE run_id=$1 AND status='pending'",
                        run_id, "Follow-up could not be enqueued",
                    )
            except Exception:
                log.warning("could not mark follow-up run failed run_id=%s", run_id, exc_info=True)
        return "failed"


def _not_found() -> HTTPException:
    return HTTPException(404, "Lead not found")


# ── Request models ────────────────────────────────────────────────────────────

class CreateLeadRequest(BaseModel):
    name:   str           = Field(..., min_length=1, max_length=200)
    email:  str | None = Field(default=None, max_length=320)
    phone:  str | None = Field(default=None, max_length=30)
    source: str | None = Field(default=None, max_length=100)


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(new|qualified|contacted|won|lost)$")


class CaptureLeadRequest(BaseModel):
    name:    str           = Field(..., min_length=1, max_length=200)
    email:   str | None = Field(default=None, max_length=320)
    phone:   str | None = Field(default=None, max_length=30)
    source:  str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=2000)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/capture", status_code=201)
async def capture_lead(
    body: CaptureLeadRequest,
    request: Request,
    key: ApiKeyRecord = Depends(require_api_key(["write"])),
    _rl: None = Depends(make_rate_limit_dep("leads_capture", max_calls=30, window=60)),
):
    """
    Public lead capture endpoint for external sources (website forms, landing pages).

    Authentication: X-API-Key: axon_<token>  OR  Authorization: ApiKey axon_<token>
    The org is derived from the API key's organization_id — never from the body.
    Returns only safe, non-internal fields.
    """
    if not key.organization_id:
        raise HTTPException(403, "API key must be scoped to an organization to capture leads")

    org_id = key.organization_id
    svc = get_lead_service()

    source = body.source or "external_capture"
    if body.message:
        source = f"{source} — {body.message[:200]}"

    lead = await svc.create(
        org_id=org_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        source=source,
    )
    lead_id = lead["id"]

    qualified_lead = await svc.qualify(lead_id=lead_id, org_id=org_id)

    follow_up_status = await _enqueue_lead_followup(
        org_id=org_id, lead_id=lead_id, triggered_by="lead_capture", user_id=None,
    )

    if qualified_lead.get("ai_tier") == "hot":
        await svc.dispatch_qualified_notification(lead=qualified_lead, org_id=org_id)

    # Return only safe fields — never expose org_id or internal state to caller
    return {
        "id": qualified_lead["id"],
        "status": qualified_lead.get("status", "new"),
        "ai_score": qualified_lead.get("ai_score"),
        "ai_tier": qualified_lead.get("ai_tier"),
        "follow_up_status": follow_up_status,
    }


@router.get("")
async def list_leads(
    status: str | None = None,
    before: str | None = None,
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

    follow_up_status = await _enqueue_lead_followup(
        org_id=ctx.org_id, lead_id=lead_id, triggered_by="lead_engine", user_id=ctx.user_id,
    )

    if qualified_lead.get("ai_tier") == "hot":
        await svc.dispatch_qualified_notification(lead=qualified_lead, org_id=ctx.org_id)

    return {**qualified_lead, "follow_up_status": follow_up_status}


class AIRequest(BaseModel):
    language: Literal["en", "ar"] = "en"


@router.post("/brief")
async def pipeline_brief(
    body: AIRequest | None = None,
    ctx: OrgContext = Depends(require_permission("leads", "write")),
):
    """Counts are exact (SQL); the AI writes the summary and picks next
    actions, each tied to a real open lead of this org."""
    try:
        return await get_lead_service().pipeline_brief(
            org_id=ctx.org_id, user_id=ctx.user_id, language=(body or AIRequest()).language,
        )
    except LeadAIError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/{lead_id}/ai-followup")
async def ai_followup(
    lead_id: str,
    body: AIRequest | None = None,
    ctx: OrgContext = Depends(require_permission("leads", "write")),
):
    try:
        draft = await get_lead_service().ai_followup(
            lead_id=lead_id, org_id=ctx.org_id, user_id=ctx.user_id,
            language=(body or AIRequest()).language,
        )
    except LeadAIError as exc:
        raise HTTPException(502, str(exc)) from None
    if draft is None:
        raise _not_found()
    return draft


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
    if lead.get("ai_tier") == "hot":
        await svc.dispatch_qualified_notification(lead=lead, org_id=ctx.org_id)
    return lead
