"""
Background Jobs API — Layer 3 surface.

POST /api/jobs                  submit a job
GET  /api/jobs                  list jobs (filterable by status/kind)
GET  /api/jobs/{id}             get job details + log
DELETE /api/jobs/{id}           cancel a running job
GET  /api/jobs/stats            aggregate counts by status

Was mounted at /jobs (no /api/ prefix, no per-route auth dependency) —
app.factory's api_auth_middleware only gates paths starting with /api/,
so every endpoint here was reachable with zero authentication. Worse than
the read-only version of this bug (chat.py/arabic_api.py/workflow_api.py):
submit_job accepted an arbitrary client-supplied payload dict verbatim,
including "organization_id" — since the queue's only registered handler
(app.integrations.sync_engine, kind="integration_sync") trusts
job.payload["organization_id"] to decide whose integration credentials
to sync, an unauthenticated caller could submit
{"kind": "integration_sync", "payload": {"organization_id": "<any org>",
"provider_id": "...", ...}} directly and trigger a real sync for an org
they have no relationship with, bypassing SyncEngine.schedule_sync()'s
own call path entirely. Now: every endpoint requires real, verified org
membership (org_context), and submit_job's payload always has its
organization_id overwritten by the server-verified one (JobQueue.submit's
org_id= kwarg), never trusting whatever the request body claims.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.jobs import get_job_queue, JobStatus
from app.tenancy.context import OrgContext, org_context

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class SubmitRequest(BaseModel):
    kind   : str
    payload: dict = {}
    ttl    : int  = 3600


@router.post("", status_code=202)
async def submit_job(body: SubmitRequest, ctx: OrgContext = Depends(org_context)):
    queue  = get_job_queue()
    job_id = await queue.submit(body.kind, payload=body.payload, ttl=body.ttl, org_id=ctx.org_id)
    return {"job_id": job_id, "status": "pending"}


@router.get("/stats")
async def job_stats(ctx: OrgContext = Depends(org_context)):
    return await get_job_queue().stats(org_id=ctx.org_id)


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    kind  : Optional[str] = None,
    limit : int = Query(50, ge=1, le=200),
    ctx: OrgContext = Depends(org_context),
):
    st    = JobStatus(status) if status else None
    jobs  = await get_job_queue().list_jobs(status=st, kind=kind, limit=limit, org_id=ctx.org_id)
    return {"jobs": [j.to_dict() for j in jobs], "total": len(jobs)}


@router.get("/{job_id}")
async def get_job(job_id: str, ctx: OrgContext = Depends(org_context)):
    job = await get_job_queue().get(job_id)
    # 404 either way (not 403) — a caller outside this org must not be
    # able to tell "doesn't exist" apart from "exists, isn't yours".
    if not job or job.payload.get("organization_id") != ctx.org_id:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return job.to_dict()


@router.delete("/{job_id}", status_code=202)
async def cancel_job(job_id: str, ctx: OrgContext = Depends(org_context)):
    queue = get_job_queue()
    job = await queue.get(job_id)
    if not job or job.payload.get("organization_id") != ctx.org_id:
        raise HTTPException(404, f"Job {job_id!r} not found")
    ok = await queue.cancel(job_id)
    if not ok:
        raise HTTPException(409, "Job cannot be cancelled in its current state")
    return {"cancelled": True, "job_id": job_id}
