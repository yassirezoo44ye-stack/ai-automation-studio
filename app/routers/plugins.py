"""
Plugin management API — Layer 13 (Plugin SDK & Extension Framework).

Endpoints:
  GET    /plugins/installed                        list this org's installed plugins   [org member]
  GET    /plugins/installed/{id}                    detail                             [org member]
  POST   /plugins/installed/{id}/enable             [plugins:manage]
  POST   /plugins/installed/{id}/disable            [plugins:manage]
  POST   /plugins/installed/{id}/approve            [plugins:manage]
  DELETE /plugins/installed/{id}                    uninstall                          [plugins:manage]
  POST   /plugins/installed/{id}/upgrade            re-load at the catalog's current version [plugins:manage]
  POST   /plugins/installed/{id}/reload             hot reload — dev only (PLUGIN_HOT_RELOAD_ENABLED=true) [plugins:manage]
  GET    /plugins/installed/{id}/config             [org member]
  PUT    /plugins/installed/{id}/config             validated against configuration_schema [plugins:manage]
  GET    /plugins/installed/{id}/health             [org member]
  GET    /plugins/installed/{id}/logs               [org member]

Installing itself is NOT a new route here — a plugin is installed via the
existing POST /marketplace/listings/{id}/install endpoint; that endpoint's
InstallationPipeline stage 7 hook (app/marketplace/installer.py) is what
actually creates the plugin_installations row this router then manages.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.plugins.loader import (
    PluginLoadError, PluginNotApprovedError, PlatformVersionError, PluginImportError,
    get_plugin_loader, normalize_installation_row,
)
from app.plugins.manifest import validate_config_against_schema
from app.tenancy import OrgContext, org_context, require_permission

router = APIRouter(prefix="/plugins", tags=["plugins"])

_LOADER_ERROR_STATUS: dict[type, int] = {
    PluginLoadError: 400,
    PluginNotApprovedError: 403,
    PlatformVersionError: 409,
    PluginImportError: 422,
}


def _raise_loader_error(exc: Exception) -> None:
    status = _LOADER_ERROR_STATUS.get(type(exc), 400)
    raise HTTPException(status_code=status, detail=str(exc))


class UpdateConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


async def _get_owned_installation(installation_id: str, org_id: str) -> dict[str, Any]:
    """404-not-403 ownership check — matches the pattern established for
    marketplace listings (_assert_owns / viewer_org_id) elsewhere in this
    codebase, so a caller can't probe which installation ids exist in
    other orgs."""
    try:
        installation_uuid = uuid.UUID(installation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Plugin installation not found")
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM plugin_installations WHERE id=$1 AND organization_id=$2",
            installation_uuid, uuid.UUID(org_id),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found")
    return normalize_installation_row(dict(row))


def _installation_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id"                 : str(row["id"]),
        "organization_id"    : str(row["organization_id"]),
        "marketplace_item_id": row["marketplace_item_id"],
        "plugin_id"          : row["plugin_id"],
        "version"            : row["version"],
        "status"             : row["status"],
        "approved"           : row["approved"],
        "config"             : row["config"],
        "manifest"           : row.get("manifest"),
        "installed_at"       : row["installed_at"],
        "updated_at"         : row["updated_at"],
    }


@router.get("/installed")
async def list_installed(ctx: OrgContext = Depends(org_context)):
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM plugin_installations WHERE organization_id=$1 ORDER BY installed_at DESC",
            uuid.UUID(ctx.org_id),
        )
    return [_installation_out(normalize_installation_row(dict(r))) for r in rows]


@router.get("/installed/{installation_id}")
async def get_installed(installation_id: str, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    return _installation_out(row)


@router.post("/installed/{installation_id}/enable")
async def enable_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    await _get_owned_installation(installation_id, ctx.org_id)
    try:
        await get_plugin_loader().enable(installation_id)
    except tuple(_LOADER_ERROR_STATUS.keys()) as exc:
        _raise_loader_error(exc)
    return {"status": "enabled", "installation_id": installation_id}


@router.post("/installed/{installation_id}/disable")
async def disable_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    await _get_owned_installation(installation_id, ctx.org_id)
    try:
        await get_plugin_loader().disable(installation_id)
    except tuple(_LOADER_ERROR_STATUS.keys()) as exc:
        _raise_loader_error(exc)
    return {"status": "disabled", "installation_id": installation_id}


@router.post("/installed/{installation_id}/approve")
async def approve_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    await _get_owned_installation(installation_id, ctx.org_id)
    try:
        await get_plugin_loader().approve(installation_id)
    except tuple(_LOADER_ERROR_STATUS.keys()) as exc:
        _raise_loader_error(exc)
    return {"status": "approved", "installation_id": installation_id}


@router.delete("/installed/{installation_id}", status_code=204)
async def uninstall_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    from app.marketplace import get_installation_pipeline
    try:
        await get_installation_pipeline().uninstall(
            row["marketplace_item_id"], org_id=ctx.org_id, actor_id=ctx.user_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/installed/{installation_id}/upgrade")
async def upgrade_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    try:
        result = await get_plugin_loader().load(row["marketplace_item_id"], org_id=ctx.org_id, actor_id=ctx.user_id)
    except tuple(_LOADER_ERROR_STATUS.keys()) as exc:
        _raise_loader_error(exc)
    return _installation_out(result)


@router.post("/installed/{installation_id}/reload")
async def reload_plugin(
    installation_id: str, ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    try:
        result = await get_plugin_loader().reload(row["marketplace_item_id"], org_id=ctx.org_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except tuple(_LOADER_ERROR_STATUS.keys()) as exc:
        _raise_loader_error(exc)
    return _installation_out(result)


@router.get("/installed/{installation_id}/config")
async def get_plugin_config(installation_id: str, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    return row["config"]


@router.put("/installed/{installation_id}/config")
async def update_plugin_config(
    installation_id: str, body: UpdateConfigRequest,
    ctx: OrgContext = Depends(require_permission("plugins", "manage")),
):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    schema = (row.get("manifest") or {}).get("configuration_schema") or {}
    errors = validate_config_against_schema(body.config, schema)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    await get_plugin_loader().update_config(installation_id, body.config)
    return {"status": "updated", "config": body.config}


@router.get("/installed/{installation_id}/health")
async def get_plugin_health(installation_id: str, ctx: OrgContext = Depends(org_context)):
    row = await _get_owned_installation(installation_id, ctx.org_id)
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        latest = await conn.fetchrow(
            "SELECT event, message, created_at FROM plugin_health_log "
            "WHERE installation_id=$1 ORDER BY created_at DESC LIMIT 1",
            uuid.UUID(installation_id),
        )
    return {
        "installation_id": installation_id,
        "status"         : row["status"],
        "last_event"     : dict(latest) if latest else None,
    }


@router.get("/installed/{installation_id}/logs")
async def get_plugin_logs(
    installation_id: str, limit: int = 50, ctx: OrgContext = Depends(org_context),
):
    await _get_owned_installation(installation_id, ctx.org_id)
    from app.core.db import get_pool
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT event, message, created_at FROM plugin_health_log "
            "WHERE installation_id=$1 ORDER BY created_at DESC LIMIT $2",
            uuid.UUID(installation_id), min(limit, 200),
        )
    return [dict(r) for r in rows]
