"""
Business Plan & Validation Engine — REST API.

Mounted at /api/business by app_main.py.

Security:
  - All writes require auth token (HMAC-verified user_id).
  - All reads use acquire_scoped(org_id) → RLS isolates tenant data.
  - Org ID is derived from the token, never from the request body.
  - Plan ownership is verified before every read/write.
  - No full plan context is sent to every agent (context packages).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.core.auth import owner_user_id
from app.core.db import get_pool, acquire_scoped
from app.core.business.models import (
    CreatePlanRequest, ExportRequest, RetryRequest,
)
from app.core.business.scoring import compute_score
from app.core.business.export import export_plan
from app.core.business.workflow import start_business_plan, retry_sections

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/business", tags=["business"])


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def _resolve_user(request: Request) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            return await owner_user_id(conn, request)
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")


async def _resolve_org(user_id: str) -> Optional[str]:
    """Return the user's primary org_id (first org they belong to)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT organization_id FROM organization_members WHERE user_id=$1 LIMIT 1",
            user_id,
        )
    return str(row["organization_id"]) if row else None


async def _assert_plan_owner(plan_id: str, user_id: str, org_id: str) -> dict:
    """Raise 404 if plan doesn't exist or doesn't belong to this user/org."""
    async with acquire_scoped(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bp_plans WHERE id=$1 AND organization_id=$2 AND user_id=$3",
            plan_id, org_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    return dict(row)


# ── Serializers ───────────────────────────────────────────────────────────────

def _plan_out(row: dict) -> dict:
    return {
        "id":              str(row["id"]),
        "title":           row.get("title", ""),
        "idea_raw":        row.get("idea_raw", ""),
        "industry":        row.get("industry"),
        "stage":           row.get("stage", "IDEA"),
        "status":          row.get("status", "DRAFT"),
        "readiness_score": row.get("readiness_score"),
        "workflow_run_id": row.get("workflow_run_id"),
        "created_at":      str(row.get("created_at", "")),
        "updated_at":      str(row.get("updated_at", "")),
    }


def _section_out(row: dict) -> dict:
    return {
        "id":           str(row["id"]),
        "plan_id":      str(row["plan_id"]),
        "section_key":  row["section_key"],
        "title":        row.get("title", ""),
        "content":      row.get("content", ""),
        "status":       row.get("status", "PENDING"),
        "agent_name":   row.get("agent_name"),
        "model_used":   row.get("model_used"),
        "tokens_used":  row.get("tokens_used", 0),
        "elapsed_ms":   row.get("elapsed_ms"),
        "retry_count":  row.get("retry_count", 0),
        "error_msg":    row.get("error_msg"),
        "updated_at":   str(row.get("updated_at", "")),
    }


def _fact_out(row: dict) -> dict:
    val = row.get("value")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            pass
    return {
        "id":          str(row["id"]),
        "plan_id":     str(row["plan_id"]),
        "fact_key":    row["fact_key"],
        "value":       val,
        "source_type": row.get("source_type", "AI_INFERENCE"),
        "source_url":  row.get("source_url"),
        "source_note": row.get("source_note"),
        "status":      row.get("status", "UNVERIFIED"),
        "confidence":  float(row.get("confidence", 0.5)),
        "section":     row.get("section"),
        "created_by":  row.get("created_by"),
        "created_at":  str(row.get("created_at", "")),
    }


def _competitor_out(row: dict) -> dict:
    def _parse_json_list(v: Any) -> list:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return []

    return {
        "id":              str(row["id"]),
        "plan_id":         str(row["plan_id"]),
        "name":            row["name"],
        "website":         row.get("website"),
        "description":     row.get("description"),
        "strengths":       _parse_json_list(row.get("strengths", "[]")),
        "weaknesses":      _parse_json_list(row.get("weaknesses", "[]")),
        "pricing":         row.get("pricing"),
        "market_position": row.get("market_position"),
        "source_url":      row.get("source_url"),
        "verified":        bool(row.get("verified", False)),
    }


def _score_out(row: dict) -> dict:
    bd = row.get("breakdown")
    if isinstance(bd, str):
        try:
            bd = json.loads(bd)
        except Exception:
            bd = {}
    return {
        "overall_score":    int(row.get("overall_score", 0)),
        "breakdown":        bd or {},
        "evidence_count":   int(row.get("evidence_count", 0)),
        "assumption_count": int(row.get("assumption_count", 0)),
        "missing_count":    int(row.get("missing_count", 0)),
        "computed_at":      str(row.get("computed_at", "")),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/plans", status_code=201)
async def create_plan(
    body: CreatePlanRequest,
    request: Request,
    background: BackgroundTasks,
) -> dict:
    """
    Create a new business plan and kick off the generation workflow
    in the background.
    """
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    async with acquire_scoped(org_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO bp_plans
                (organization_id, user_id, idea_raw, industry, stage, status)
            VALUES ($1,$2,$3,$4,$5,'DRAFT')
            RETURNING *
            """,
            org_id, user_id,
            body.idea_raw.strip(),
            body.industry,
            body.stage.value,
        )
    plan_id = str(row["id"])

    # Kick off workflow in background (non-blocking)
    background.add_task(
        _run_workflow_bg,
        plan_id=plan_id, org_id=org_id, user_id=user_id,
        idea_raw=body.idea_raw.strip(),
        industry=body.industry,
        stage=body.stage.value,
    )

    return _plan_out(dict(row))


async def _run_workflow_bg(
    plan_id: str, org_id: str, user_id: str,
    idea_raw: str, industry: Optional[str], stage: str,
) -> None:
    """Background task: run the full BUSINESS_PLAN_ENGINE workflow."""
    try:
        await start_business_plan(plan_id, org_id, user_id, idea_raw, industry, stage)
    except Exception as exc:
        log.exception("business_plan workflow failed for plan %s: %s", plan_id, exc)
        async with acquire_scoped(org_id) as conn:
            await conn.execute(
                "UPDATE bp_plans SET status='FAILED', updated_at=NOW() WHERE id=$1",
                plan_id,
            )


@router.get("/plans")
async def list_plans(request: Request) -> list[dict]:
    """List all plans for the authenticated user."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        return []

    async with acquire_scoped(org_id) as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM bp_plans
            WHERE organization_id=$1 AND user_id=$2
            ORDER BY updated_at DESC LIMIT 50
            """,
            org_id, user_id,
        )
    return [_plan_out(dict(r)) for r in rows]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, request: Request) -> dict:
    """Full plan detail: metadata + sections + facts + competitors + score."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    async with acquire_scoped(org_id) as conn:
        plan_row = await conn.fetchrow("SELECT * FROM bp_plans WHERE id=$1", plan_id)
        sections = await conn.fetch(
            "SELECT * FROM bp_sections WHERE plan_id=$1 ORDER BY created_at", plan_id,
        )
        facts = await conn.fetch(
            "SELECT * FROM bp_facts WHERE plan_id=$1 ORDER BY created_at", plan_id,
        )
        competitors = await conn.fetch(
            "SELECT * FROM bp_competitors WHERE plan_id=$1 ORDER BY created_at", plan_id,
        )
        score_row = await conn.fetchrow(
            "SELECT * FROM bp_scores WHERE plan_id=$1 ORDER BY computed_at DESC LIMIT 1",
            plan_id,
        )

    return {
        "plan":        _plan_out(dict(plan_row)),
        "sections":    [_section_out(dict(r)) for r in sections],
        "facts":       [_fact_out(dict(r))    for r in facts],
        "competitors": [_competitor_out(dict(r)) for r in competitors],
        "score":       _score_out(dict(score_row)) if score_row else None,
    }


@router.get("/plans/{plan_id}/stream")
async def stream_plan_status(plan_id: str, request: Request) -> StreamingResponse:
    """
    SSE stream of plan generation progress.
    Emits section status updates and the final score.
    """
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    async def _generator():
        import asyncio
        pool = get_pool()
        seen_statuses: dict[str, str] = {}
        terminal = {"COMPLETED", "FAILED", "PAUSED"}

        for _ in range(120):  # max 2 min polling
            async with pool.acquire() as conn:
                plan_row = await conn.fetchrow(
                    "SELECT status, readiness_score FROM bp_plans WHERE id=$1", plan_id,
                )
                sections  = await conn.fetch(
                    "SELECT section_key, status, tokens_used, error_msg FROM bp_sections WHERE plan_id=$1",
                    plan_id,
                )

            payload: dict[str, Any] = {}
            for s in sections:
                key = s["section_key"]
                if seen_statuses.get(key) != s["status"]:
                    seen_statuses[key] = s["status"]
                    payload[key] = {
                        "status":      s["status"],
                        "tokens_used": s["tokens_used"],
                        "error_msg":   s["error_msg"],
                    }

            if payload or plan_row["status"] in terminal:
                data = json.dumps({
                    "plan_status":    plan_row["status"],
                    "readiness_score": plan_row["readiness_score"],
                    "sections":       payload,
                })
                yield f"data: {data}\n\n"

            if plan_row["status"] in terminal:
                yield "data: {\"done\": true}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/plans/{plan_id}/retry")
async def retry_plan_sections(
    plan_id: str,
    body: RetryRequest,
    request: Request,
    background: BackgroundTasks,
) -> dict:
    """Fix Loop: re-run only the specified failing sections."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    plan = await _assert_plan_owner(plan_id, user_id, org_id)

    background.add_task(
        retry_sections,
        plan_id=plan_id, org_id=org_id, user_id=user_id,
        idea_raw=plan.get("idea_raw", ""),
        industry=plan.get("industry"),
        stage=plan.get("stage", "IDEA"),
        section_keys=body.section_keys,
    )
    return {"message": "Retry started", "section_keys": body.section_keys}


@router.post("/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str, request: Request) -> dict:
    """Pause/cancel a running plan generation."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE bp_plans SET status='PAUSED', updated_at=NOW() WHERE id=$1",
            plan_id,
        )
    return {"message": "Plan paused"}


@router.post("/plans/{plan_id}/score")
async def recompute_score(plan_id: str, request: Request) -> dict:
    """Recompute the Business Readiness Score on demand."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    async with acquire_scoped(org_id) as conn:
        score = await compute_score(conn, plan_id, org_id)
    return score


@router.post("/plans/{plan_id}/export")
async def export_plan_endpoint(
    plan_id: str,
    body: ExportRequest,
    request: Request,
) -> Response:
    """Export the business plan as Markdown (PDF/DOCX: coming soon)."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    async with acquire_scoped(org_id) as conn:
        try:
            content, filename, mime = await export_plan(
                conn, plan_id, body.format, body.variant,
            )
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc))

    return Response(
        content=content.encode("utf-8"),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str, request: Request) -> None:
    """Delete a business plan and all related data (cascades via FK)."""
    user_id = await _resolve_user(request)
    org_id  = await _resolve_org(user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization")

    await _assert_plan_owner(plan_id, user_id, org_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bp_plans WHERE id=$1", plan_id)
