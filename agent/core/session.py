"""
Flow Device Agent — Session State

Tracks the agent's current session membership:
  - Which control session this device belongs to
  - The layout of all devices in the session
  - Whether this device is the primary or a secondary
  - Per-session authorization token (short-lived, revoked on session stop)

Lifecycle:
  IDLE → ENROLLED → ACTIVE → IDLE

Not OS-specific. No input logic here.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class SessionMember:
    """One device's slot in a control session."""
    device_id: str
    is_primary: bool
    position_x: int
    position_y: int
    width: int
    height: int
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "device_id":  self.device_id,
            "is_primary": self.is_primary,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "width":      self.width,
            "height":     self.height,
            "enabled":    self.enabled,
        }


class AgentSessionState:
    """
    Thread-safe session state for the device agent.

    Updated when the server sends:
      - session_start  → set session details, activate
      - layout_update  → update member positions
      - session_stop   → clear session, go idle
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session_id:    Optional[str]  = None
        self._session_token: Optional[str]  = None
        self._is_primary:    bool            = False
        self._members:       list[SessionMember] = []
        self._active:        bool            = False
        self._workspace_id:  Optional[str]  = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def session_id(self) -> Optional[str]:
        with self._lock:
            return self._session_id

    @property
    def session_token(self) -> Optional[str]:
        with self._lock:
            return self._session_token

    @property
    def is_primary(self) -> bool:
        with self._lock:
            return self._is_primary

    @property
    def members(self) -> list[dict]:
        """Return a safe copy of all member dicts."""
        with self._lock:
            return [m.as_dict() for m in self._members]

    @property
    def layout(self) -> list[dict]:
        """Alias for members — used by the edge-detection algorithm."""
        return self.members

    @property
    def workspace_id(self) -> Optional[str]:
        with self._lock:
            return self._workspace_id

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def apply_session_start(self, msg: dict, our_device_id: str) -> None:
        """
        Called when the server sends a session_start frame.

        Expected frame fields:
          session_id, session_token, workspace_id, members (list of member dicts)
        """
        with self._lock:
            self._session_id    = msg.get("session_id")
            self._session_token = msg.get("session_token")
            self._workspace_id  = msg.get("workspace_id")
            self._active        = True

            raw_members = msg.get("members", [])
            self._members = [
                SessionMember(
                    device_id  = m["device_id"],
                    is_primary = m.get("is_primary", False),
                    position_x = m.get("position_x", 0),
                    position_y = m.get("position_y", 0),
                    width      = m.get("width", 1920),
                    height     = m.get("height", 1080),
                    enabled    = m.get("enabled", True),
                )
                for m in raw_members
            ]

            # Determine our own role
            our_member = next((m for m in self._members if m.device_id == our_device_id), None)
            self._is_primary = our_member.is_primary if our_member else False

        log.info(
            "session_start applied session_id=%s is_primary=%s members=%d",
            self._session_id, self._is_primary, len(raw_members),
        )

    def apply_layout_update(self, msg: dict) -> None:
        """
        Called when the server sends a layout_update frame.

        Allows the admin to rearrange devices mid-session without stopping it.
        """
        with self._lock:
            if not self._active:
                return
            raw_members = msg.get("members", [])
            self._members = [
                SessionMember(
                    device_id  = m["device_id"],
                    is_primary = m.get("is_primary", False),
                    position_x = m.get("position_x", 0),
                    position_y = m.get("position_y", 0),
                    width      = m.get("width", 1920),
                    height     = m.get("height", 1080),
                    enabled    = m.get("enabled", True),
                )
                for m in raw_members
            ]

        log.info("layout_update applied members=%d", len(raw_members))

    def apply_session_stop(self, reason: str = "") -> None:
        """Called when the session ends (server, failsafe, or primary disconnect)."""
        with self._lock:
            sid = self._session_id
            self._session_id    = None
            self._session_token = None
            self._is_primary    = False
            self._members       = []
            self._active        = False
            self._workspace_id  = None

        log.info("session_stop applied session_id=%s reason=%s", sid, reason)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def get_member(self, device_id: str) -> Optional[dict]:
        with self._lock:
            m = next((m for m in self._members if m.device_id == device_id), None)
            return m.as_dict() if m else None

    def member_count(self) -> int:
        with self._lock:
            return len(self._members)

    def enabled_member_count(self) -> int:
        with self._lock:
            return sum(1 for m in self._members if m.enabled)
