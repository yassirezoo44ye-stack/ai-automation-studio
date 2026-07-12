"""
Agent Sandbox API — Layer 14 (Agent Sandbox & Secure Execution Runtime).

Endpoints:
  GET    /sandbox/workers                              list this org's sandbox workers        [org member]
  GET    /sandbox/workers/{id}                          detail                                 [org member]
  GET    /sandbox/workers/{id}/logs                      sandbox_events for this worker          [org member]
  GET    /sandbox/workers/{id}/resource-usage            cpu/memory peak columns                 [org member]
  POST   /sandbox/workers/{id}/stop                      force-terminate                        [plugins:manage]
  GET    /sandbox/security-events                       org-wide sandbox_events, event_type=security [org member]
  GET    /sandbox/permission-requests                   plugin_installations awaiting approval  [org member]
  POST   /sandbox/permission-requests/{installation_id}/approve  [plugins:manage]

No new permission-declaration table — a "permission request" IS Plugin
SDK's existing plugin_installations.approved=false + a sensitive
plugin_permissions row, just surfaced under this page; approving one
calls the existing PluginLoader.approve() directly.

A sandbox worker's own lifecycle IS its plugin_installations row's
lifecycle (one worker per installation — see app/sandbox/schema.py's
UNIQUE(plugin_installation_id)), so ownership/ACL here always routes
through organization_id on sandbox_workers directly, matching the
_get_owned_installation pattern in app/routers/plugins.py.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.tenancy import OrgContext, org_context, require_permission

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


async def _get_owned_worker(worker_id: str, org_id: str) -> dict[str, Any]:
    try:
        worker_uuid = uuid.UUID(worker_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sandbox worker not found")
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sandbox_workers WHERE id=$1 AND organization_id=$2",
            worker_uuid, uuid.UUID(org_id),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Sandbox worker not found")
    return dict(row)


def _worker_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id"                    : str(row["id"]),
        "organization_id"       : str(row["organization_id"]),
        "plugin_installation_id": str(row["plugin_installation_id"]),
        "backend"               : row["backend"],
        "status"                : row["status"],
        "pid_or_container_id"   : row["pid_or_container_id"],
        "started_at"            : row["started_at"],
        "stopped_at"            : row["stopped_at"],
        "cpu_seconds_used"      : row["cpu_seconds_used"],
        "memory_mb_peak"        : row["memory_mb_peak"],
    }


@router.get("/workers")
async def list_workers(ctx: OrgContext = Depends(org_context)):
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sandbox_workers WHERE organization_id=$1 ORDER BY started_at DESC",
            uuid.UUID(ctx.org_id),
        )
    return [_worker_out(dict(r)) for r in rows]


@router.get("/workers/{worker_id}")
async def get_worker_detail(worker_id: str, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_worker(worker_id, ctx.org_id)
    return _worker_out(row)


@router.get("/workers/{worker_id}/logs")
async def get_worker_logs(worker_id: str, limit: int = 50, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_worker(worker_id, ctx.org_id)
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_type, severity, message, details, created_at FROM sandbox_events "
            "WHERE worker_id=$1 ORDER BY created_at DESC LIMIT $2",
            row["id"], min(limit, 200),
        )
    return [dict(r) for r in rows]


@router.get("/workers/{worker_id}/resource-usage")
async def get_worker_resource_usage(worker_id: str, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_worker(worker_id, ctx.org_id)
    return {
        "worker_id"       : str(row["id"]),
        "backend"         : row["backend"],
        "status"          : row["status"],
        "cpu_seconds_used": row["cpu_seconds_used"],
        "memory_mb_peak"  : row["memory_mb_peak"],
    }


@router.post("/workers/{worker_id}/stop")
async def stop_worker(worker_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage"))):
    row = await _get_owned_worker(worker_id, ctx.org_id)
    from app.sandbox import get_sandbox_manager
    await get_sandbox_manager().stop_worker(str(row["plugin_installation_id"]))
    return {"status": "stopped", "worker_id": worker_id}


@router.get("/security-events")
async def list_security_events(limit: int = 50, ctx: OrgContext = Depends(org_context)):
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, worker_id, severity, message, details, created_at FROM sandbox_events "
            "WHERE organization_id=$1 AND event_type='security' ORDER BY created_at DESC LIMIT $2",
            uuid.UUID(ctx.org_id), min(limit, 200),
        )
    return [dict(r) for r in rows]


@router.get("/permission-requests")
async def list_permission_requests(ctx: OrgContext = Depends(org_context)):
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT pi.id, pi.plugin_id, pi.version, pi.status, pi.manifest,
                      array_agg(pp.capability) FILTER (WHERE pp.granted=false) AS pending_capabilities
               FROM plugin_installations pi
               JOIN plugin_permissions pp ON pp.installation_id = pi.id
               WHERE pi.organization_id=$1 AND pi.approved=false AND pp.granted=false
               GROUP BY pi.id""",
            uuid.UUID(ctx.org_id),
        )
    return [
        {
            "installation_id": str(r["id"]), "plugin_id": r["plugin_id"], "version": r["version"],
            "status": r["status"], "pending_capabilities": r["pending_capabilities"] or [],
        }
        for r in rows
    ]


@router.post("/permission-requests/{installation_id}/approve")
async def approve_permission_request(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    try:
        installation_uuid = uuid.UUID(installation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Plugin installation not found")
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM plugin_installations WHERE id=$1 AND organization_id=$2",
            installation_uuid, uuid.UUID(ctx.org_id),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found")
    from app.plugins.loader import get_plugin_loader
    await get_plugin_loader().approve(installation_id)
    return {"status": "approved", "installation_id": installation_id}
