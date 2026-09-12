"""
Device Control HTTP API — /api/devices and /api/device-sessions.

All endpoints are organization-scoped via OrgContext.
All write operations require explicit RBAC permissions.
Enrollment token generation and device revocation are audit-logged.

BLOCKER 2 FALLBACK: GET /api/devices/{id}/session-token lets an agent that
reconnects after a session was already started fetch a fresh session auth token
authenticated only by its device credential (HTTP Basic Auth, no browser JWT).
The raw token is returned once over TLS and is NEVER logged.
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.tenancy.context import OrgContext, require_permission
from app.services.device_control import get_device_control_service, DEVICE_CONTROL_ENABLED

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["device-control"])
sessions_router = APIRouter(prefix="/api/device-sessions", tags=["device-control"])


def _check_enabled() -> None:
    if not DEVICE_CONTROL_ENABLED:
        raise HTTPException(503, "Device Control feature is disabled on this server")


# ── Request / Response models ─────────────────────────────────────────────────

class EnrollmentTokenResponse(BaseModel):
    token_id: str
    token: str
    prefix: str
    expires_in: int
    expires_at: float


class EnrollRequest(BaseModel):
    """Sent by the Flow Device Agent to consume an enrollment token."""
    token: str = Field(..., min_length=10)
    device_name: str = Field(..., min_length=1, max_length=120)
    platform: str = Field("windows")
    hostname: Optional[str] = Field(None, max_length=255)
    agent_version: Optional[str] = Field(None, max_length=40)
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    device_fingerprint: Optional[str] = Field(None, max_length=128)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"windows", "macos", "linux", "unknown"}
        if v not in allowed:
            raise ValueError(f"platform must be one of {allowed}")
        return v


class CreateSessionRequest(BaseModel):
    primary_device_id: str
    device_ids: list[str] = Field(..., min_length=1, max_length=5)
    workspace_id: Optional[str] = None

    @field_validator("device_ids")
    @classmethod
    def validate_uuids(cls, v: list[str]) -> list[str]:
        for d in v:
            try:
                uuid.UUID(d)
            except ValueError:
                raise ValueError(f"Invalid UUID: {d}")
        return v

    @field_validator("primary_device_id")
    @classmethod
    def validate_primary_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("primary_device_id must be a valid UUID")
        return v


class LayoutItem(BaseModel):
    device_id: str
    position_x: int = 0
    position_y: int = 0
    width: int = Field(1920, ge=1)
    height: int = Field(1080, ge=1)
    sort_order: int = 0
    enabled: bool = True


class UpdateLayoutRequest(BaseModel):
    layout: list[LayoutItem] = Field(..., min_length=1)


# ── Device endpoints ──────────────────────────────────────────────────────────

@router.get("/")
async def list_devices(ctx: OrgContext = require_permission("devices", "read")):  # type: ignore[assignment]
    """List all active (non-revoked) devices in the organization."""
    _check_enabled()
    svc = get_device_control_service()
    return await svc.list_devices(ctx.org_id)


@router.get("/{device_id}")
async def get_device(
    device_id: str,
    ctx: OrgContext = require_permission("devices", "read"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    device = await svc.get_device(ctx.org_id, device_id)
    if device is None:
        raise HTTPException(404, "Device not found")
    return device


@router.post("/enroll-token")
async def create_enrollment_token(
    request: Request,
    ctx: OrgContext = require_permission("devices", "create"),  # type: ignore[assignment]
):
    """
    Generate a single-use enrollment token for registering a new device.
    The raw token is returned exactly once — never stored in plaintext.
    """
    _check_enabled()
    svc = get_device_control_service()
    workspace_id = request.query_params.get("workspace_id")
    result = await svc.create_enrollment_token(
        org_id=ctx.org_id,
        created_by_user_id=ctx.user_id,
        created_by_email=ctx.user_email,
        workspace_id=workspace_id or None,
    )
    return result


@router.post("/enroll")
async def enroll_device(body: EnrollRequest):
    """
    Consume an enrollment token and register a device.
    Called by the Flow Device Agent (not by the browser UI).
    Returns a device credential (shown once — never re-issued without rotation).

    Note: this endpoint is intentionally NOT protected by org_context because
    the agent does not yet have an organization identity — that is established
    by consuming the enrollment token, which is org-bound.
    """
    _check_enabled()
    svc = get_device_control_service()
    try:
        result = await svc.consume_enrollment_token(
            raw_token=body.token,
            device_name=body.device_name,
            platform=body.platform,
            hostname=body.hostname,
            agent_version=body.agent_version,
            screen_width=body.screen_width,
            screen_height=body.screen_height,
            device_fingerprint=body.device_fingerprint,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@router.post("/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    ctx: OrgContext = require_permission("devices", "revoke"),  # type: ignore[assignment]
):
    """
    Permanently revoke a device. The device credential is invalidated and
    the agent WebSocket is terminated. The device cannot reconnect without
    re-enrolling.
    """
    _check_enabled()
    svc = get_device_control_service()
    try:
        await svc.revoke_device(ctx.org_id, device_id, ctx.user_email)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "revoked"}


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    ctx: OrgContext = require_permission("devices", "delete"),  # type: ignore[assignment]
):
    """Delete (revoke) a device. Alias for revoke for REST completeness."""
    _check_enabled()
    svc = get_device_control_service()
    try:
        await svc.revoke_device(ctx.org_id, device_id, ctx.user_email)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "deleted"}


@router.post("/{device_id}/rotate-credential")
async def rotate_device_credential(
    device_id: str,
    ctx: OrgContext = require_permission("devices", "update"),  # type: ignore[assignment]
):
    """
    Issue a new device credential, invalidating the old one.
    The agent must re-authenticate on its next connection.
    """
    _check_enabled()
    svc = get_device_control_service()
    try:
        result = await svc.rotate_credential(ctx.org_id, device_id, ctx.user_email)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


# ── Agent-only token fetch (BLOCKER 2 fallback) ───────────────────────────────

@router.get("/{device_id}/session-token")
async def get_device_session_token(
    device_id: str,
    session_id: str,
    request: Request,
):
    """
    Fallback for agents that reconnect AFTER a session has already been started.

    When an agent was offline during start_session(), the server stored its token
    hash in device_session_authorizations but could not deliver the raw token.
    This endpoint lets the agent exchange its device credential for a fresh raw
    token so it can authenticate on the WebSocket.

    Authentication: HTTP Basic Auth using (device_id, credential) — same
    credential stored via DPAPI on the agent, verified by SHA-256 hash comparison.
    NO browser JWT is used here; this endpoint is machine-to-machine only.

    SECURITY:
      • credential verified by SHA-256 hash comparison — plaintext never stored
      • raw session_token returned exactly once over TLS
      • response is NEVER cached (Cache-Control: no-store)
      • token bound to this specific (device_id, session_id) pair
      • NEVER log the returned token value
    """
    _check_enabled()

    # Parse HTTP Basic Auth: Authorization: Basic base64(device_id:credential)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        raise HTTPException(
            401,
            "Device credential required (HTTP Basic Auth: device_id:credential)",
            headers={"WWW-Authenticate": "Basic realm=\"Flow Device Agent\""},
        )
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        basic_device_id, raw_credential = decoded.split(":", 1)
    except Exception:
        raise HTTPException(401, "Malformed Basic auth header")

    # Enforce that the URL device_id matches the credential's owner
    if basic_device_id != device_id:
        raise HTTPException(403, "device_id mismatch")

    svc = get_device_control_service()

    # Verify device credential (SHA-256 comparison — same as WS auth)
    device_info = await svc.authenticate_device(device_id, raw_credential)
    if device_info is None:
        raise HTTPException(401, "Invalid device credential")

    org_id = device_info["organization_id"]

    # Issue / rotate token for this (device, session) pair
    raw_tok = await svc.get_session_token_for_device(org_id, session_id, device_id)
    if raw_tok is None:
        raise HTTPException(
            403,
            "Device is not an enabled member of this active session",
        )

    # Return raw token; never log it here or anywhere in the call chain
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"session_token": raw_tok},   # raw — NEVER LOG
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# ── Session endpoints ─────────────────────────────────────────────────────────

@sessions_router.get("/")
async def list_sessions(ctx: OrgContext = require_permission("device_sessions", "read")):  # type: ignore[assignment]
    _check_enabled()
    svc = get_device_control_service()
    return await svc.list_sessions(ctx.org_id)


@sessions_router.post("/")
async def create_session(
    body: CreateSessionRequest,
    ctx: OrgContext = require_permission("device_sessions", "create"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    try:
        session = await svc.create_session(
            org_id=ctx.org_id,
            created_by_user_id=ctx.user_id,
            created_by_email=ctx.user_email,
            primary_device_id=body.primary_device_id,
            device_ids=body.device_ids,
            workspace_id=body.workspace_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return session


@sessions_router.get("/{session_id}")
async def get_session(
    session_id: str,
    ctx: OrgContext = require_permission("device_sessions", "read"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    session = await svc.get_session(ctx.org_id, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


@sessions_router.post("/{session_id}/start")
async def start_session(
    session_id: str,
    ctx: OrgContext = require_permission("device_sessions", "control"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    try:
        session = await svc.start_session(ctx.org_id, session_id, ctx.user_email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return session


@sessions_router.post("/{session_id}/stop")
async def stop_session(
    session_id: str,
    ctx: OrgContext = require_permission("device_sessions", "control"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    try:
        await svc.stop_session(ctx.org_id, session_id, ctx.user_email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "stopped"}


@sessions_router.patch("/{session_id}/layout")
async def update_layout(
    session_id: str,
    body: UpdateLayoutRequest,
    ctx: OrgContext = require_permission("device_sessions", "control"),  # type: ignore[assignment]
):
    _check_enabled()
    svc = get_device_control_service()
    try:
        await svc.update_layout(
            ctx.org_id, session_id,
            [item.model_dump() for item in body.layout],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "updated"}
