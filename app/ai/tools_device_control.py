"""
Device-Control tools for AgentOS / AgentRuntime tool loops.

Registration: import this module during startup (app/factory.py) to
register all tools into the platform-wide _REGISTRY via the @tool()
decorator. Tools are available to any AgentConfig that lists their names.

Security model
--------------
org_id is NEVER a tool parameter — the LLM cannot supply or modify it.
Instead, callers MUST set the org_id context variable before starting a
tool loop that uses these tools:

    from app.ai.tools_device_control import set_device_control_context
    set_device_control_context(org_id=ctx.org_id, user_id=ctx.user_id,
                               user_email=ctx.user_email)

The context variables are cleared automatically when the async task ends.
Any tool that reads an empty org_id returns an authorization error.

What the LLM CAN do through these tools:
  - List online devices (metadata only — no credentials)
  - Validate a proposed session configuration
  - Create a DRAFT session (does NOT start it — human approval required)
  - Query the status of an existing session
  - Stop a session that is already active

What the LLM CANNOT do:
  - Start a session (requires human approval via UI)
  - Generate or view enrollment tokens
  - Read device credentials or session auth tokens
  - Issue WebSocket control frames
  - Access devices from other organizations
  - Access raw keyboard or mouse event data
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Optional

from app.ai.tools import tool

log = logging.getLogger(__name__)

# ── Org-scoped context (set by agent, never by LLM) ───────────────────────────

_dc_org_id_var:    ContextVar[str] = ContextVar("dc_org_id",    default="")
_dc_user_id_var:   ContextVar[str] = ContextVar("dc_user_id",   default="")
_dc_user_email_var: ContextVar[str] = ContextVar("dc_user_email", default="")


def set_device_control_context(
    *,
    org_id: str,
    user_id: str,
    user_email: str,
) -> None:
    """
    Bind device-control tools to a verified organization / user for this
    asyncio task. Call this from agent code BEFORE starting any tool loop
    that exposes device-control tools.

    The bound values come from the JWT-verified OrgContext or AgentContext —
    never from user/LLM input.
    """
    _dc_org_id_var.set(org_id)
    _dc_user_id_var.set(user_id)
    _dc_user_email_var.set(user_email)


def _require_context() -> tuple[str, str, str]:
    """Return (org_id, user_id, user_email) or raise a ValueError."""
    org_id     = _dc_org_id_var.get()
    user_id    = _dc_user_id_var.get()
    user_email = _dc_user_email_var.get()
    if not org_id:
        raise ValueError(
            "Device-control tools require an organization context. "
            "The calling agent must invoke set_device_control_context() "
            "before starting a tool loop."
        )
    return org_id, user_id, user_email


def _safe_device(row: dict) -> dict:
    """Return only safe, non-sensitive device fields for LLM consumption."""
    return {
        "id":           row.get("id"),
        "name":         row.get("name"),
        "platform":     row.get("platform"),
        "hostname":     row.get("hostname"),
        "status":       row.get("status"),
        "screen_width": row.get("screen_width"),
        "screen_height": row.get("screen_height"),
        "last_seen_at": str(row.get("last_seen_at") or ""),
        "agent_version": row.get("agent_version"),
    }
    # Explicitly excluded: credential_hash, device_fingerprint, revoked_at,
    # display_config (large, unnecessary), capabilities (internal).


def _safe_session(row: dict) -> dict:
    """Return only safe session fields — no secrets."""
    return {
        "id":                row.get("id"),
        "status":            row.get("status"),
        "primary_device_id": row.get("primary_device_id"),
        "device_count":      row.get("device_count"),
        "created_at":        str(row.get("created_at") or ""),
        "started_at":        str(row.get("started_at") or ""),
        "stopped_at":        str(row.get("stopped_at") or ""),
        "stop_reason":       row.get("stop_reason"),
    }
    # Explicitly excluded: session_token, authorization tokens.


# ── Tool: list devices ─────────────────────────────────────────────────────────

@tool(
    name="device_control_list_devices",
    description=(
        "List the devices registered to the current organization that are eligible "
        "for multi-device control sessions. Returns metadata only — no credentials, "
        "no secrets. Filter by status to find online devices ready to be added to a "
        "session. Maximum 5 devices may participate in one session (including primary)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["online", "offline", "all"],
                "description": "Filter devices by status. Use 'online' to find devices ready for a session.",
                "default": "online",
            },
        },
        "required": [],
    },
)
async def device_control_list_devices(status_filter: str = "online") -> str:
    try:
        org_id, _, _ = _require_context()
        from app.services.device_control import get_device_control_service
        svc = get_device_control_service()
        devices = await svc.list_devices(org_id)

        if status_filter != "all":
            devices = [d for d in devices if d.get("status") == status_filter]

        safe_devices = [_safe_device(d) for d in devices]

        # Emit discovery event (best-effort)
        try:
            from app.core.ai.events.bus import bus
            from app.core.ai.events.device_control_events import DeviceControlDiscoveryRun
            await bus.emit(DeviceControlDiscoveryRun(
                organization_id=org_id,
                devices_found=len(safe_devices),
                requested_by="device_control_agent",
            ))
        except Exception:
            pass

        return json.dumps({
            "devices": safe_devices,
            "count": len(safe_devices),
            "max_per_session": 5,
            "note": (
                "Up to 5 devices per session (including primary). "
                "Device IDs from this list are the only valid inputs for "
                "device_control_validate_session and device_control_propose_session."
            ),
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        log.error("device_control_list_devices failed: %s", e, exc_info=True)
        return json.dumps({"error": "Failed to list devices. Check server logs."})


# ── Tool: validate session configuration ───────────────────────────────────────

@tool(
    name="device_control_validate_session",
    description=(
        "Validate a proposed multi-device control session configuration WITHOUT "
        "creating it. Use this before proposing a session to confirm all devices "
        "are eligible. Returns validation errors if any device is invalid, revoked, "
        "from a different organization, or if the device count exceeds the limit of 5."
    ),
    parameters={
        "type": "object",
        "properties": {
            "primary_device_id": {
                "type": "string",
                "description": "UUID of the device that will capture input (the operator's machine).",
            },
            "target_device_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
                "description": "UUIDs of up to 4 secondary devices that will receive input.",
            },
        },
        "required": ["primary_device_id", "target_device_ids"],
    },
)
async def device_control_validate_session(
    primary_device_id: str,
    target_device_ids: list[str],
) -> str:
    try:
        org_id, _, _ = _require_context()
        from app.services.device_control import get_device_control_service, MAX_DEVICES_PER_SESSION

        errors: list[str] = []

        # Deduplicate and count
        all_ids = list({primary_device_id, *target_device_ids})
        total = len(all_ids)

        if total > MAX_DEVICES_PER_SESSION:
            errors.append(
                f"Total device count {total} exceeds the maximum of "
                f"{MAX_DEVICES_PER_SESSION} (primary + targets combined)."
            )

        if not primary_device_id:
            errors.append("primary_device_id is required.")

        if errors:
            return json.dumps({"valid": False, "errors": errors})

        # Fetch devices from DB — verifies org membership and revocation status
        svc = get_device_control_service()
        devices = await svc.list_devices(org_id)
        device_map = {d["id"]: d for d in devices}

        # Check primary
        if primary_device_id not in device_map:
            errors.append(
                f"Primary device '{primary_device_id}' not found in this "
                "organization or has been revoked."
            )

        # Check targets
        for did in target_device_ids:
            if did == primary_device_id:
                continue   # primary already checked
            if did not in device_map:
                errors.append(
                    f"Target device '{did}' not found in this organization or "
                    "has been revoked."
                )

        if errors:
            return json.dumps({"valid": False, "errors": errors})

        # Build summary
        devices_summary = []
        for did in all_ids:
            d = device_map[did]
            devices_summary.append({
                "id":     did,
                "name":   d["name"],
                "status": d["status"],
                "role":   "primary" if did == primary_device_id else "secondary",
            })

        return json.dumps({
            "valid": True,
            "total_devices": total,
            "max_devices": MAX_DEVICES_PER_SESSION,
            "devices": devices_summary,
            "next_step": (
                "Configuration is valid. Call device_control_propose_session to "
                "create a draft session for human review and approval."
            ),
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        log.error("device_control_validate_session failed: %s", e, exc_info=True)
        return json.dumps({"error": "Validation failed. Check server logs."})


# ── Tool: propose session (creates DRAFT — does NOT start) ────────────────────

@tool(
    name="device_control_propose_session",
    description=(
        "Create a DRAFT multi-device control session for human review. "
        "The session is NOT started automatically — a human operator must review "
        "the proposed configuration in the Flow UI and explicitly click 'Start Session' "
        "to activate it. This tool only creates a draft record. "
        "Always call device_control_validate_session first to confirm eligibility."
    ),
    parameters={
        "type": "object",
        "properties": {
            "primary_device_id": {
                "type": "string",
                "description": "UUID of the primary (input-capturing) device.",
            },
            "target_device_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
                "description": "UUIDs of up to 4 secondary devices.",
            },
            "session_name": {
                "type": "string",
                "maxLength": 120,
                "description": "Optional human-readable name for this session.",
            },
        },
        "required": ["primary_device_id", "target_device_ids"],
    },
)
async def device_control_propose_session(
    primary_device_id: str,
    target_device_ids: list[str],
    session_name: Optional[str] = None,
) -> str:
    try:
        org_id, user_id, user_email = _require_context()

        if not user_id:
            return json.dumps({"error": "User context required to propose a session."})

        from app.services.device_control import get_device_control_service
        svc = get_device_control_service()

        # create_session() enforces: org membership, device count ≤ 5,
        # no revoked devices, all devices belong to this org.
        # The session is created in 'draft' status — NOT started.
        session = await svc.create_session(
            org_id=org_id,
            created_by_user_id=user_id,
            created_by_email=user_email,
            primary_device_id=primary_device_id,
            device_ids=target_device_ids,
            workspace_id=None,
        )

        session_id = session["id"]

        # Emit proposal event (best-effort)
        try:
            from app.core.ai.events.bus import bus
            from app.core.ai.events.device_control_events import DeviceControlSessionProposed
            await bus.emit(DeviceControlSessionProposed(
                session_id=session_id,
                organization_id=org_id,
                primary_device_id=primary_device_id,
                device_count=len({primary_device_id, *target_device_ids}),
                proposed_by_agent="device_control_agent",
                session_name=session_name,
            ))
        except Exception:
            pass

        return json.dumps({
            "session_id":  session_id,
            "status":      session.get("status", "draft"),
            "device_count": session.get("device_count", 0),
            "approval_required": True,
            "message": (
                f"Draft session '{session_id}' created successfully. "
                "A human operator must open the Flow UI → Devices page "
                "and click 'Start Session' to activate control. "
                "This agent cannot start the session automatically."
            ),
            "ui_action": "Navigate to Flow UI → Devices → Sessions → Start Session",
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        log.error("device_control_propose_session failed: %s", e, exc_info=True)
        return json.dumps({"error": "Failed to propose session. Check server logs."})


# ── Tool: session status ───────────────────────────────────────────────────────

@tool(
    name="device_control_session_status",
    description=(
        "Get the current status of a multi-device control session. "
        "Returns session metadata (status, device count, timestamps) — "
        "never returns credentials or session auth tokens."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "UUID of the session to query.",
            },
        },
        "required": ["session_id"],
    },
)
async def device_control_session_status(session_id: str) -> str:
    try:
        org_id, _, _ = _require_context()
        from app.services.device_control import get_device_control_service
        svc = get_device_control_service()
        session = await svc.get_session(org_id, session_id)
        if session is None:
            return json.dumps({"error": f"Session '{session_id}' not found in this organization."})
        return json.dumps(_safe_session(session))
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        log.error("device_control_session_status failed: %s", e, exc_info=True)
        return json.dumps({"error": "Failed to get session status."})


# ── Tool: stop session ─────────────────────────────────────────────────────────

@tool(
    name="device_control_stop_session",
    description=(
        "Stop an active multi-device control session. This releases all "
        "input hooks on every device and returns control to local operation. "
        "Stopping is a safety operation that can be performed by an agent — "
        "unlike starting, which requires explicit human approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "UUID of the session to stop.",
            },
        },
        "required": ["session_id"],
    },
)
async def device_control_stop_session(session_id: str) -> str:
    try:
        org_id, _, user_email = _require_context()
        from app.services.device_control import get_device_control_service
        svc = get_device_control_service()
        await svc.stop_session(org_id, session_id, user_email or "agent@system")

        # Emit stopped event (best-effort)
        try:
            from app.core.ai.events.bus import bus
            from app.core.ai.events.device_control_events import DeviceControlSessionStopped
            await bus.emit(DeviceControlSessionStopped(
                session_id=session_id,
                organization_id=org_id,
                stop_reason="agent_requested",
            ))
        except Exception:
            pass

        return json.dumps({
            "session_id": session_id,
            "status": "stopped",
            "message": "Session stopped successfully. All devices have restored local input control.",
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        log.error("device_control_stop_session failed: %s", e, exc_info=True)
        return json.dumps({"error": "Failed to stop session. Check server logs."})


# ── Tool names exposed to agents ───────────────────────────────────────────────

DEVICE_CONTROL_TOOL_NAMES: tuple[str, ...] = (
    "device_control_list_devices",
    "device_control_validate_session",
    "device_control_propose_session",
    "device_control_session_status",
    "device_control_stop_session",
)

__all__ = [
    "set_device_control_context",
    "DEVICE_CONTROL_TOOL_NAMES",
]
