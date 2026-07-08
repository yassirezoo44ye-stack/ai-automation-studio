"""
Background Jobs API — Layer 3 surface.

POST /jobs                  submit a job
GET  /jobs                  list jobs (filterable by status/kind)
GET  /jobs/{id}             get job details + log
DELETE /jobs/{id}           cancel a running job
GET  /jobs/stats            aggregate counts by status
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.jobs import get_job_queue, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


class SubmitRequest(BaseModel):
    kind   : str
    payload: dict = {}
    ttl    : int  = 3600


@router.post("", status_code=202)
async def submit_job(body: SubmitRequest):
    queue  = get_job_queue()
    job_id = await queue.submit(body.kind, payload=body.payload, ttl=body.ttl)
    return {"job_id": job_id, "status": "pending"}


@router.get("/stats")
async def job_stats():
    return await get_job_queue().stats()


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    kind  : Optional[str] = None,
    limit : int = Query(50, ge=1, le=200),
):
    st    = JobStatus(status) if status else None
    jobs  = await get_job_queue().list_jobs(status=st, kind=kind, limit=limit)
    return {"jobs": [j.to_dict() for j in jobs], "total": len(jobs)}


@router.get("/{job_id}")
async def get_job(job_id: str):
    job = await get_job_queue().get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return job.to_dict()


@router.delete("/{job_id}", status_code=202)
async def cancel_job(job_id: str):
    ok = await get_job_queue().cancel(job_id)
    if not ok:
        raise HTTPException(409, "Job cannot be cancelled in its current state")
    return {"cancelled": True, "job_id": job_id}
