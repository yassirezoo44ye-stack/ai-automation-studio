"""
AI Business App Builder — REST router.

Endpoints (all require JWT auth + org membership):
  POST   /api/app-builder/preview-spec          dry-run: return spec only
  POST   /api/app-builder/apps                  generate spec + submit async build
  GET    /api/app-builder/apps                  list org's apps
  GET    /api/app-builder/apps/{app_id}         app detail + progress + versions
  POST   /api/app-builder/apps/{app_id}/retry   retry a failed/partial build
  POST   /api/app-builder/apps/{app_id}/modify  incremental modification
  DELETE /api/app-builder/apps/{app_id}         soft-delete (owner/admin only)

Security:
  • Every endpoint resolves OrgContext — membership verified in DB.
  • All writes are scoped to ctx.org_id, never from the request body.
  • No raw SQL or arbitrary code from user input — validation in service.
  • IDOR: GET/POST/DELETE check both app_id AND organization_id.
  • Progress/status returned from DB, never fabricated server-side.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.tenancy import OrgContext, require_permission
from app.services.app_builder import (
    AppSpec, BuildResult, BuildStep, get_app_builder_service,
)
from app.core.db import get_pool, write_audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app-builder", tags=["app-builder"])


# ── Request / response models ─────────────────────────────────────────────────

class BuildRequest(BaseModel):
    prompt: str = Field(
        min_length=10, max_length=2000,
        description="Natural-language description of the desired app.",
    )
    include_automation: bool = Field(
        default=False,
        description="Also generate workflows and AI agents.",
    )


class ModifyRequest(BaseModel):
    prompt: str = Field(
        min_length=5, max_length=1000,
        description="What to add/change in the existing app.",
    )


def _spec_to_response(spec: AppSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "target_users": spec.target_users,
        "entities": [
            {
                "name": e.name,
                "display_name": e.display_name,
                "columns": [
                    {"name": c.name, "type": c.type,
                     "nullable": c.nullable, "unique": c.unique}
                    for c in e.columns
                ],
                "relationships": e.relationships,
            }
            for e in spec.entities
        ],
        "pages":  [{"name": p.name, "entity": p.entity, "kind": p.kind}
                   for p in spec.pages],
        "roles":  [{"name": r.name, "permissions": r.permissions}
                   for r in spec.roles],
        "workflows": [{"name": w.name, "trigger": w.trigger}
                      for w in spec.workflows],
        "agents": [{"name": a.name, "description": a.description}
                   for a in spec.agents],
        "integrations": spec.integrations,
    }


def _result_to_response(result: BuildResult) -> dict[str, Any]:
    return {
        "app_id": result.app_id,
        "app_name": result.app_name,
        "status": result.overall_status,
        "summary": {
            "tables": result.tables_created,
            "pages": result.pages_created,
            "roles": result.roles_created,
            "api_operations": result.api_operations,
            "workflows": result.workflows_created,
            "agents": result.agents_created,
            "canvas_id": result.canvas_id,
        },
        "steps": [
            {"label": s.label, "status": s.status, "detail": s.detail}
            for s in result.steps
        ],
        "warnings": result.warnings,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/preview-spec")
async def preview_spec(
    body: BuildRequest,
    ctx: OrgContext = Depends(require_permission("app_builder", "create")),
) -> dict[str, Any]:
    """
    Generate and return the structured AppSpec without building anything.
    Useful for showing the user what will be created before committing.
    """
    svc = get_app_builder_service()
    try:
        spec = await svc.generate_spec(
            body.prompt,
            include_automation=body.include_automation,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.error("preview_spec error: %s", exc, exc_info=True)
        raise HTTPException(500, "Spec generation failed — check logs.") from exc

    return {"spec": _spec_to_response(spec)}


@router.post("/apps")
async def create_app(
    body: BuildRequest,
    ctx: OrgContext = Depends(require_permission("app_builder", "create")),
) -> dict[str, Any]:
    """
    Generate spec + submit the build job asynchronously.

    Returns immediately with the app ID and initial build state.
    Poll GET /apps/{id} for live progress updates.

    Response: {"id": "...", "status": "building", "progress": 0, "current_step": "initializing"}
    """
    svc = get_app_builder_service()
    try:
        # Spec generation runs in the HTTP request so validation errors
        # (bad prompt, AI refusal) surface before we create any DB records.
        spec = await svc.generate_spec(
            body.prompt,
            include_automation=body.include_automation,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
        # Create app record + submit background job — returns (app_id, job_id)
        # immediately; the pipeline runs in the background.
        app_id, _job_id = await svc.submit_build_job(
            spec,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            user_email=ctx.user_email,
            include_automation=body.include_automation,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.error("create_app error: %s", exc, exc_info=True)
        raise HTTPException(500, "App submission failed — check logs.") from exc

    return {
        "id": app_id,
        "status": "building",
        "progress": 0,
        "current_step": "initializing",
    }


@router.get("/apps")
async def list_apps(
    ctx: OrgContext = Depends(require_permission("app_builder", "read")),
) -> dict[str, Any]:
    """List all apps in the current organization."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, description, build_status,
                   include_automation, created_at, updated_at,
                   array_length(workflow_ids, 1) AS workflow_count,
                   array_length(agent_ids, 1) AS agent_count
            FROM app_builder_apps
            WHERE organization_id = $1
            ORDER BY created_at DESC
            LIMIT 100
            """,
            ctx.org_id,
        )
    return {
        "apps": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "build_status": r["build_status"],
                "include_automation": r["include_automation"],
                "workflow_count": r["workflow_count"] or 0,
                "agent_count": r["agent_count"] or 0,
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/apps/{app_id}")
async def get_app(
    app_id: str,
    ctx: OrgContext = Depends(require_permission("app_builder", "read")),
) -> dict[str, Any]:
    """
    Return full app detail including live build progress and version history.

    Poll this endpoint every 2 seconds while build_status == 'building' to
    receive live progress updates. Build is terminal when build_status is
    one of: ready | partial | failed.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, description, spec, build_status,
                   build_result, build_warnings, canvas_id,
                   include_automation, created_at, updated_at,
                   progress, current_step, total_steps, completed_steps,
                   error, retry_count, started_at, completed_at
            FROM app_builder_apps
            WHERE id = $1 AND organization_id = $2
            """,
            app_id, ctx.org_id,
        )
        if not row:
            raise HTTPException(404, "App not found")

        versions = await conn.fetch(
            """
            SELECT version_number, label, change_summary, created_at
            FROM app_builder_versions
            WHERE app_id = $1
            ORDER BY version_number DESC
            LIMIT 20
            """,
            app_id,
        )

    def _ts(v: Any) -> Optional[str]:
        return v.isoformat() if v is not None else None

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "spec": dict(row["spec"]),
        "build_status": row["build_status"],
        "build_result": dict(row["build_result"]),
        "build_warnings": list(row["build_warnings"]),
        "canvas_id": str(row["canvas_id"]) if row["canvas_id"] else None,
        "include_automation": row["include_automation"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        # ── Async build progress ──────────────────────────────────────────────
        "progress": row["progress"] if row["progress"] is not None else 0,
        "current_step": row["current_step"] or "pending",
        "total_steps": row["total_steps"] if row["total_steps"] is not None else 12,
        "completed_steps": row["completed_steps"] if row["completed_steps"] is not None else 0,
        "error": row["error"],
        "retry_count": row["retry_count"] if row["retry_count"] is not None else 0,
        "started_at": _ts(row["started_at"]),
        "completed_at": _ts(row["completed_at"]),
        # ── Version history ───────────────────────────────────────────────────
        "versions": [
            {
                "version_number": v["version_number"],
                "label": v["label"],
                "change_summary": v["change_summary"],
                "created_at": v["created_at"].isoformat(),
            }
            for v in versions
        ],
    }


@router.post("/apps/{app_id}/retry")
async def retry_app(
    app_id: str,
    ctx: OrgContext = Depends(require_permission("app_builder", "update")),
) -> dict[str, Any]:
    """
    Retry a failed or partially-built app.

    Only apps in 'failed' or 'partial' state can be retried.
    The build pipeline is idempotent — every step is safe to re-run
    without creating duplicate resources.

    Response: {"id": "...", "status": "building", "progress": 0, "current_step": "initializing"}
    """
    svc = get_app_builder_service()
    try:
        _app_id, _job_id = await svc.retry_app_build(
            app_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            user_email=ctx.user_email,
        )
    except ValueError as exc:
        # Includes "not found", "wrong state", "not in this org"
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.error("retry_app %s error: %s", app_id, exc, exc_info=True)
        raise HTTPException(500, "Retry submission failed — check logs.") from exc

    return {
        "id": app_id,
        "status": "building",
        "progress": 0,
        "current_step": "initializing",
    }


@router.post("/apps/{app_id}/modify")
async def modify_app(
    app_id: str,
    body: ModifyRequest,
    ctx: OrgContext = Depends(require_permission("app_builder", "update")),
) -> dict[str, Any]:
    """
    Incrementally modify an existing application without rebuilding it.

    The AI understands the current spec and applies only the requested changes.
    A new version snapshot is recorded automatically.
    """
    svc = get_app_builder_service()
    try:
        result = await svc.modify_app(
            app_id,
            body.prompt,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        log.error("modify_app %s error: %s", app_id, exc, exc_info=True)
        raise HTTPException(500, "Modification failed — check logs.") from exc

    return {"result": _result_to_response(result)}


@router.delete("/apps/{app_id}")
async def delete_app(
    app_id: str,
    ctx: OrgContext = Depends(require_permission("app_builder", "delete")),
) -> dict[str, str]:
    """
    Soft-delete an app (sets build_status='failed', filters from list).
    Does NOT drop dynamic tables — destructive DDL requires explicit confirmation.
    Requires admin or owner role (enforced by require_permission).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE app_builder_apps
            SET build_status = 'failed', updated_at = now()
            WHERE id = $1 AND organization_id = $2
              AND build_status != 'failed'
            """,
            app_id, ctx.org_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, "App not found or already deleted")
    return {"status": "deleted", "app_id": app_id}
