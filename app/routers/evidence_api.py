"""
Engineering Evidence API.

Endpoints:
  GET /api/engineering/missions/{id}/evidence     — list all evidence for a mission
  GET /api/engineering/evidence/{id}              — get single evidence record

Evidence records are immutable audit logs of external tool calls.
Credentials and raw secrets are NEVER included in evidence output.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.tenancy.context import OrgContext, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engineering", tags=["engineering"])


@router.get("/missions/{mission_id}/evidence")
async def list_mission_evidence(
    mission_id: str,
    limit: int = Query(50, ge=1, le=200),
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """List all evidence records for a mission, newest first."""
    from app.engineering.evidence import get_evidence_store
    store = get_evidence_store()
    records = await store.list_for_mission(
        mission_id, org_id=ctx.org_id, limit=limit
    )
    return {"evidence": records, "count": len(records)}


@router.get("/evidence/{evidence_id}")
async def get_evidence(
    evidence_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """Get a single evidence record by ID."""
    from app.engineering.evidence import get_evidence_store
    store = get_evidence_store()
    record = await store.get(evidence_id, org_id=ctx.org_id)
    if record is None:
        raise HTTPException(404, "evidence not found")
    return record


@router.get("/missions/{mission_id}/verified")
async def mission_verification_status(
    mission_id: str,
    ctx: OrgContext = Depends(require_permission("engineering", "read")),
) -> dict[str, Any]:
    """
    Return whether this mission has all deploy operations verified.

    Used by the UI dashboard to display:
      DEVELOPMENT            — no CI steps run
      PRODUCTION CANDIDATE   — CI + PR + deploy triggered
      PRODUCTION VERIFIED    — sha_match=True + health=True for all deploys
    """
    from app.engineering.evidence import get_evidence_store
    store = get_evidence_store()
    verified = await store.has_verified_deploy(mission_id, org_id=ctx.org_id)
    return {
        "mission_id":           mission_id,
        "all_deploys_verified": verified,
        "classification":       "PRODUCTION VERIFIED" if verified else "PRODUCTION CANDIDATE",
    }
