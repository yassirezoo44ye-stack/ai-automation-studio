"""Every endpoint requires verified org membership AND scopes data to user_id.
Organization colleagues cannot read each other's CV, mailbox, drafts or jobs.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.careers.gmail import GmailUnavailable
from app.core.careers.models import (
    CareerProfile,
    ImportAlert,
    JobStatus,
    OAuthExchange,
    ScheduleSettings,
)
from app.core.careers.service import CareerService
from app.core.rate_limit import make_rate_limit_dep
from app.tenancy.context import OrgContext, org_context

router = APIRouter(
    prefix="/api/careers",
    tags=["career-assistant"],
    dependencies=[
        Depends(make_rate_limit_dep("careers", max_calls=30, window=60)),
    ],
)


def service():
    from app.core.db import get_pool

    return CareerService(get_pool())


@router.get("/profile")
async def get_profile(ctx: Annotated[OrgContext, Depends(org_context)]):
    return await service().profile(ctx)


@router.put("/profile")
async def save_profile(
    body: CareerProfile, ctx: Annotated[OrgContext, Depends(org_context)]
):
    return await service().save_profile(ctx, body)


@router.get("/jobs")
async def list_jobs(ctx: Annotated[OrgContext, Depends(org_context)]):
    return {"items": await service().jobs(ctx), "limit": 500}


@router.post("/import")
async def import_alert(
    body: ImportAlert, ctx: Annotated[OrgContext, Depends(org_context)]
):
    return await service().import_alert(ctx, body)


@router.patch("/jobs/{job_id}/status")
async def update_status(
    job_id: uuid.UUID, body: JobStatus, ctx: Annotated[OrgContext, Depends(org_context)]
):
    if not await service().status(ctx, job_id, body.status):
        raise HTTPException(404, "Job not found")
    return {"status": body.status}


@router.post("/jobs/{job_id}/draft")
async def draft(job_id: uuid.UUID, ctx: Annotated[OrgContext, Depends(org_context)]):
    text = await service().draft(ctx, job_id)
    if text is None:
        raise HTTPException(404, "Job not found")
    return {"text": text, "sent": False}


@router.post("/jobs/{job_id}/verify")
async def verify(job_id: uuid.UUID, ctx: Annotated[OrgContext, Depends(org_context)]):
    import json

    from app.core.careers.verify import verify_listing

    svc = service()
    job = await svc.job(ctx, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    checked = await verify_listing(job)
    async with svc.pool.acquire() as conn:
        await conn.execute(
            "UPDATE career_jobs SET data=$4::jsonb,updated_at=now() WHERE organization_id=$1 AND user_id=$2 AND id=$3",
            *svc.owner(ctx),
            job_id,
            json.dumps(checked),
        )
    return {"verification": checked["verification"]}


@router.get("/gmail")
async def connection(ctx: Annotated[OrgContext, Depends(org_context)]):
    return await service().connection(ctx)


@router.post("/gmail/connect")
async def connect(ctx: Annotated[OrgContext, Depends(org_context)]):
    try:
        return await service().oauth_begin(ctx)
    except GmailUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.post("/gmail/exchange")
async def exchange(
    body: OAuthExchange, ctx: Annotated[OrgContext, Depends(org_context)]
):
    try:
        await service().oauth_finish(ctx, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except GmailUnavailable as exc:
        raise HTTPException(502, str(exc)) from None
    return {"connected": True}


@router.post("/gmail/sync")
async def sync(ctx: Annotated[OrgContext, Depends(org_context)]):
    try:
        return await service().sync(ctx)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except GmailUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


@router.put("/gmail/schedule")
async def schedule(
    body: ScheduleSettings, ctx: Annotated[OrgContext, Depends(org_context)]
):
    try:
        await service().schedule(ctx, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return body


@router.delete("/gmail")
async def disconnect(ctx: Annotated[OrgContext, Depends(org_context)]):
    await service().disconnect(ctx)
    return {"connected": False}
