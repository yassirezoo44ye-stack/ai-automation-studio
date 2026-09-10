"""
Flow Device Agent — Control Protocol v1

All frames are JSON. Version must be 1.

SECURITY:
  - Never log vk (virtual-key code) or scan code values.
  - Never persist key_down / key_up payloads.
  - Never include raw input in exceptions or traces.
  - Mouse coordinates are transient — never stored.

Frame ordering:
  - key_down / key_up preserve the seq counter for ordering guarantee.
  - mouse_down / mouse_up preserve ordering (sent immediately).
  - mouse_move may be coalesced at the transport layer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

PROTOCOL_VERSION = 1


# ── Outgoing (Agent → Server) ─────────────────────────────────────────────────

@dataclass
class AuthFrame:
    device_id: str
    credential: str
    session_id: Optional[str] = None
    session_token: Optional[str] = None
    type: str = "auth"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":       self.version,
            "type":          self.type,
            "device_id":     self.device_id,
            "credential":    self.credential,
            "session_id":    self.session_id,
            "session_token": self.session_token,
        }


@dataclass
class HeartbeatFrame:
    type: str = "heartbeat"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":   self.version,
            "type":      self.type,
            "timestamp": int(time.time() * 1000),
        }


@dataclass
class MouseMoveFrame:
    x: int
    y: int
    type: str = "mouse_move"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":   self.version,
            "type":      self.type,
            "x":         self.x,
            "y":         self.y,
            "timestamp": int(time.time() * 1000),
        }


@dataclass
class MouseButtonFrame:
    button: int   # 0=left, 1=right, 2=middle
    x: int
    y: int
    action: str   # "down" | "up"
    version: int = PROTOCOL_VERSION

    @property
    def type(self) -> str:
        return f"mouse_{self.action}"

    def to_dict(self) -> dict:
        return {
            "version":   self.version,
            "type":      self.type,
            "button":    self.button,
            "x":         self.x,
            "y":         self.y,
            "timestamp": int(time.time() * 1000),
        }


@dataclass
class MouseScrollFrame:
    dx: int
    dy: int
    type: str = "mouse_scroll"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":   self.version,
            "type":      self.type,
            "dx":        self.dx,
            "dy":        self.dy,
            "timestamp": int(time.time() * 1000),
        }


@dataclass
class KeyFrame:
    vk: int       # Virtual-key code — NEVER LOG THIS VALUE
    scan: int     # Hardware scan code — NEVER LOG THIS VALUE
    flags: int    # Extended flags
    seq: int      # Monotonic sequence number for ordering
    action: str   # "down" | "up"
    version: int = PROTOCOL_VERSION

    @property
    def type(self) -> str:
        return f"key_{self.action}"

    def to_dict(self) -> dict:
        # vk and scan are included only in the wire frame — never in logs
        return {
            "version":   self.version,
            "type":      self.type,
            "vk":        self.vk,
            "scan":      self.scan,
            "flags":     self.flags,
            "seq":       self.seq,
            "timestamp": int(time.time() * 1000),
        }


@dataclass
class DisplayConfigFrame:
    monitors: list[dict]
    primary_width: int
    primary_height: int
    type: str = "display_config"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":       self.version,
            "type":          self.type,
            "monitors":      self.monitors,
            "primary_width": self.primary_width,
            "primary_height": self.primary_height,
            "timestamp":     int(time.time() * 1000),
        }


@dataclass
class DeviceSwitchFrame:
    from_device: str
    to_device: str
    cursor_x: int
    cursor_y: int
    type: str = "device_switch"
    version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict:
        return {
            "version":     self.version,
            "type":        self.type,
            "from_device": self.from_device,
            "to_device":   self.to_device,
            "cursor_x":    self.cursor_x,
            "cursor_y":    self.cursor_y,
            "timestamp":   int(time.time() * 1000),
        }


# ── Frame validation ──────────────────────────────────────────────────────────

_VALID_INCOMING_TYPES = frozenset({
    "auth_ok", "auth_fail",
    "session_start", "session_stop",
    "device_switch", "device_focus",
    "heartbeat_ack",
    "error",
    # Forwarded from primary to secondary agents:
    "mouse_move", "mouse_down", "mouse_up", "mouse_scroll",
    "key_down", "key_up",
})


def validate_incoming(msg: dict) -> bool:
    """Validate a frame received FROM the server."""
    if not isinstance(msg, dict):
        return False
    if msg.get("version") != PROTOCOL_VERSION:
        return False
    if msg.get("type") not in _VALID_INCOMING_TYPES:
        return False
    return True
