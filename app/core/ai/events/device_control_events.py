"""
Device-control lifecycle events for the AI event bus.

These events bridge the Multi-Device Control service and the AgentOS /
App Builder layer. They follow the same AIEvent dataclass pattern used
throughout `app/core/ai/events/events.py`.

Payload rules (enforced by convention, not code — keep them):
  - NEVER include credential_hash, session_token, enrollment tokens, or
    any WebSocket secrets.
  - NEVER include raw keyboard virtual-key codes (vk) or scan codes.
  - NEVER include raw mouse coordinates from control-loop frames.
  - Safe metadata only: IDs, names, counts, timestamps, status strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.ai.events.events import AIEvent  # reuse helpers


# ── Session proposed (draft created by AgentOS) ───────────────────────────────

@dataclass
class DeviceControlSessionProposed(AIEvent):
    """
    Emitted when an AgentOS agent creates a DRAFT device-control session.
    The session remains in 'draft' status until a human explicitly starts
    it via the Flow UI — the agent can never start it directly.
    """
    event_type:         str           = "device_control.session.proposed"
    session_id:         str           = ""
    organization_id:    str           = ""
    primary_device_id:  str           = ""
    device_count:       int           = 0
    proposed_by_agent:  str           = ""      # agent name, never a user credential
    session_name:       Optional[str] = None


# ── Session approved (human approved via UI) ──────────────────────────────────

@dataclass
class DeviceControlSessionApproved(AIEvent):
    """
    Emitted when a human approves and starts a previously-drafted session
    via the authorized Flow UI (POST /api/device-sessions/{id}/start).
    """
    event_type:      str = "device_control.session.approved"
    session_id:      str = ""
    organization_id: str = ""
    approved_by:     str = ""     # user email — not a credential


# ── Session started (transitioned to active) ──────────────────────────────────

@dataclass
class DeviceControlSessionStarted(AIEvent):
    event_type:      str = "device_control.session.started"
    session_id:      str = ""
    organization_id: str = ""
    device_count:    int = 0


# ── Session stopped ───────────────────────────────────────────────────────────

@dataclass
class DeviceControlSessionStopped(AIEvent):
    event_type:      str           = "device_control.session.stopped"
    session_id:      str           = ""
    organization_id: str           = ""
    stop_reason:     Optional[str] = None


# ── Session failed ────────────────────────────────────────────────────────────

@dataclass
class DeviceControlSessionFailed(AIEvent):
    event_type:      str = "device_control.session.failed"
    session_id:      str = ""
    organization_id: str = ""
    error:           str = ""


# ── Device discovered by agent ───────────────────────────────────────────────

@dataclass
class DeviceControlDiscoveryRun(AIEvent):
    """
    Emitted when an agent queries the device list on behalf of a user.
    Carries only the count — never individual device credentials or IDs
    from unverified sources.
    """
    event_type:      str = "device_control.discovery.run"
    organization_id: str = ""
    devices_found:   int = 0
    requested_by:    str = ""    # agent name


__all__ = [
    "DeviceControlSessionProposed",
    "DeviceControlSessionApproved",
    "DeviceControlSessionStarted",
    "DeviceControlSessionStopped",
    "DeviceControlSessionFailed",
    "DeviceControlDiscoveryRun",
]
