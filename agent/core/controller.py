"""
Flow Device Agent — Core Controller

Orchestrates:
  - WebSocket connection lifecycle
  - Input hook management (Windows)
  - Session state machine
  - Failsafe triggers
  - Edge detection and device switching (primary agent only)
  - Display configuration reporting
  - Tray icon state updates

Session state machine:
  IDLE → CONNECTING → AUTHENTICATED → CONTROL_ACTIVE → IDLE

CRITICAL SAFETY:
  - On ANY error, disconnect, or failsafe activation → release all hooks
    and restore local input BEFORE attempting any network operation.
  - The failsafe hotkey path MUST be network-independent.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import sys
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Never log input values — only state transitions
_STATE_LOG = logging.getLogger(__name__ + ".state")

AGENT_VERSION = "1.0.0"


class AgentState:
    IDLE          = "idle"
    CONNECTING    = "connecting"
    CONNECTED     = "connected"
    CONTROL_ACTIVE = "control_active"
    STOPPING      = "stopping"
    REVOKED       = "revoked"


class DeviceAgentController:
    """
    Central controller for the Flow Device Agent.

    Usage:
      agent = DeviceAgentController(device_id, credential, server_url)
      await agent.run()
    """

    def __init__(
        self,
        device_id: str,
        credential: str,
        server_url: str,
        device_name: str = "",
        is_primary: bool = False,
        on_state_change: Optional[Callable[[str], None]] = None,
    ):
        self._device_id = device_id
        self._credential = credential   # NEVER LOGGED
        self._server_url = server_url
        self._device_name = device_name
        self._is_primary = is_primary
        self._on_state_change = on_state_change

        self._state = AgentState.IDLE
        self._session_id: Optional[str] = None
        self._ws_client = None
        self._hook_manager = None
        self._pump_thread: Optional[threading.Thread] = None
        self._stop_event = asyncio.Event()
        self._control_active = False

        # Layout: list of dicts with device_id, position_x, position_y, width, height
        self._layout: list[dict] = []
        self._current_device_id: Optional[str] = None  # which device has focus

    # ── State management ────────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        _STATE_LOG.info("state: %s → %s", self._state, state)
        self._state = state
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception:
                pass

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_control_active(self) -> bool:
        return self._control_active

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main agent loop — connect, authenticate, handle messages."""
        from agent.transport.websocket_client import DeviceWebSocketClient

        self._set_state(AgentState.CONNECTING)

        self._ws_client = DeviceWebSocketClient(
            server_url=self._server_url,
            device_id=self._device_id,
            credential=self._credential,
            on_message=self._on_server_message,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )

        # Report display configuration on connect
        await self._report_display_config()

        try:
            await self._ws_client.run()
        finally:
            self._release_control("connection_ended")
            self._set_state(AgentState.IDLE)

    def stop(self) -> None:
        """Signal the agent to stop cleanly."""
        self._release_control("user_stop")
        self._set_state(AgentState.STOPPING)
        if self._ws_client:
            self._ws_client.stop()
        self._stop_event.set()

    # ── Connection callbacks ────────────────────────────────────────────────

    def _on_connected(self) -> None:
        self._set_state(AgentState.CONNECTED)
        _STATE_LOG.info("agent connected device_id=%s", self._device_id)

    def _on_disconnected(self) -> None:
        # FAILSAFE: release all hooks FIRST before updating state
        self._release_control("disconnected")
        if self._state not in (AgentState.STOPPING, AgentState.REVOKED):
            self._set_state(AgentState.IDLE)

    # ── Server message handling ─────────────────────────────────────────────

    def _on_server_message(self, msg: dict) -> None:
        """Handle a frame received from the server."""
        mtype = msg.get("type", "")

        if mtype == "session_start":
            # BLOCKER 2 FIX: persist session_id + session_token from the personalized frame
            new_sid = msg.get("session_id")
            if new_sid:
                self._session_id = new_sid
            new_tok = msg.get("session_token")  # raw token — NEVER log this value
            if new_sid and new_tok and self._ws_client:
                self._ws_client.set_session(new_sid, new_tok)

            # BLOCKER 3 FIX: populate layout so edge-detection geometry is available
            members = msg.get("members")
            if members and isinstance(members, list):
                self._layout = members
            # is_primary may be overridden by the server (the server knows who is primary)
            if "is_primary" in msg:
                self._is_primary = bool(msg["is_primary"])
            # Cursor starts on our own screen
            self._current_device_id = self._device_id

            _STATE_LOG.info(
                "session_start received session_id=%s is_primary=%s members=%d",
                self._session_id,
                self._is_primary,
                len(self._layout),
            )
            if self._is_primary:
                self._activate_control_primary()
            else:
                self._activate_control_secondary()

        elif mtype == "session_stop":
            reason = msg.get("reason", "")
            _STATE_LOG.info("session_stop received reason=%s", reason)
            # FAILSAFE: release hooks BEFORE any other processing
            self._release_control(reason)
            if reason == "device_revoked":
                self._set_state(AgentState.REVOKED)

        elif mtype == "device_switch":
            if not self._is_primary:
                # Secondary: accept the new cursor position
                tx = msg.get("cursor_x", 0)
                ty = msg.get("cursor_y", 0)
                self._warp_cursor(tx, ty)

        elif mtype in ("mouse_move", "mouse_down", "mouse_up", "mouse_scroll",
                        "key_down", "key_up"):
            # Secondary device: inject the received input
            # NEVER log vk, scan, or coordinates
            if not self._is_primary and self._control_active:
                self._inject_input(msg)

        # Other message types (auth_ok, heartbeat_ack, error) are handled
        # in the transport layer or ignored safely.

    # ── Input capture (PRIMARY device) ─────────────────────────────────────

    def _activate_control_primary(self) -> None:
        """
        Primary device: install hooks to capture and forward input.
        Local input is NOT suppressed — it is captured and forwarded.
        """
        if sys.platform != "win32":
            log.warning("primary control not supported on %s yet", sys.platform)
            return

        from agent.windows.input import WindowsInputHookManager, run_message_pump

        self._hook_manager = WindowsInputHookManager(
            on_mouse_move=self._forward_mouse_move,
            on_mouse_button=self._forward_mouse_button,
            on_mouse_scroll=self._forward_mouse_scroll,
            on_key=self._forward_key,
            on_failsafe=self._on_failsafe,
            is_primary=True,
        )

        # Install hooks in the message-pump thread (required by Windows)
        def _install_and_pump():
            self._hook_manager.install()
            run_message_pump()

        self._pump_thread = threading.Thread(
            target=_install_and_pump, daemon=True, name="flow-input-pump"
        )
        self._pump_thread.start()
        self._control_active = True
        self._set_state(AgentState.CONTROL_ACTIVE)
        _STATE_LOG.info("primary control ACTIVATED")

    def _activate_control_secondary(self) -> None:
        """
        Secondary device: install hooks to suppress local input
        (so injected commands don't re-trigger the hook).
        """
        if sys.platform != "win32":
            log.warning("secondary control not supported on %s yet", sys.platform)
            return

        from agent.windows.input import WindowsInputHookManager, run_message_pump

        self._hook_manager = WindowsInputHookManager(
            on_mouse_move=lambda x, y: None,       # ignore captured events
            on_mouse_button=lambda b, a, x, y: None,
            on_mouse_scroll=lambda dx, dy: None,
            on_key=lambda vk, sc, fl, ac: None,    # ignore — we inject instead
            on_failsafe=self._on_failsafe,
            is_primary=False,   # enables suppression
        )

        def _install_and_pump():
            self._hook_manager.install()
            run_message_pump()

        self._pump_thread = threading.Thread(
            target=_install_and_pump, daemon=True, name="flow-input-pump"
        )
        self._pump_thread.start()
        self._control_active = True
        self._set_state(AgentState.CONTROL_ACTIVE)
        _STATE_LOG.info("secondary control ACTIVATED — local input suppressed")

    def _release_control(self, reason: str) -> None:
        """
        FAILSAFE: Release all hooks and restore normal local input.
        This MUST complete even if the network is unavailable.
        """
        if not self._control_active:
            return

        _STATE_LOG.warning("releasing control reason=%s", reason)

        # Step 1: Release hooks (network-independent)
        if self._hook_manager:
            try:
                self._hook_manager.uninstall()
            except Exception as e:
                log.error("hook uninstall error: %s", type(e).__name__)
            self._hook_manager = None

        # Step 2: Clear state
        self._control_active = False
        self._current_device_id = None

        if self._state not in (AgentState.STOPPING, AgentState.REVOKED):
            self._set_state(AgentState.CONNECTED)

        _STATE_LOG.warning("control RELEASED — local input restored")

    # ── Input forwarding (PRIMARY → Server → Secondary) ─────────────────────

    def _forward_mouse_move(self, x: int, y: int) -> None:
        """Forward mouse position to server. Never persisted. Never logged.

        BLOCKER 3 FIX: the original code called _check_edge_crossing() then
        returned unconditionally, so mouse_move frames were NEVER forwarded
        after a device switch.  The fix separates two concerns:

          A. Edge detection  — detect if cursor crossed a monitor boundary and
             update self._current_device_id accordingly (may emit device_switch).
          B. Forwarding      — send mouse_move only when cursor is on a secondary
             device (current_device_id ≠ own device_id).

        When the cursor is still on the primary (our own screen) there is no
        secondary device to inject on, so we simply return.
        """
        if not self._ws_client:
            return

        if self._is_primary:
            # Primary agent: never forward blindly — only when cursor is on secondary.
            # If layout is empty (session_start not yet received), nothing to do.
            if self._layout:
                # A. Edge detection — check for boundary crossing, update current device
                if self._current_device_id:
                    self._check_edge_crossing(x, y)

                # B. Forwarding — only when cursor is on a secondary device
                if (
                    self._current_device_id
                    and self._current_device_id != self._device_id
                ):
                    frame = {"version": 1, "type": "mouse_move", "x": x, "y": y,
                              "timestamp": int(time.time() * 1000)}
                    asyncio.create_task(self._ws_client.send(frame))
            # Always return early for primary (either no layout, or cursor on our screen)
            return

        # Non-primary (secondary/injection path) — forward unconditionally
        frame = {"version": 1, "type": "mouse_move", "x": x, "y": y,
                  "timestamp": int(time.time() * 1000)}
        asyncio.create_task(self._ws_client.send(frame))

    def _check_edge_crossing(self, x: int, y: int) -> None:
        """
        Detect if the cursor has crossed a screen edge and trigger a device switch.
        Uses layout geometry to determine the target device.
        """
        from agent.core.layout import detect_edge_crossing, compute_switch
        result = detect_edge_crossing(
            x, y, self._layout, self._current_device_id
        )
        if result is not None:
            direction, target = result
            switch = compute_switch(
                x, y, self._layout, self._current_device_id, target
            )
            if switch:
                self._current_device_id = switch["to_device"]   # K.1.5 FIX: string, not dict
                frame = {
                    "version":     1,
                    "type":        "device_switch",
                    "from_device": switch["from_device"],
                    "to_device":   switch["to_device"],
                    "cursor_x":    switch["target_x"],
                    "cursor_y":    switch["target_y"],
                    "timestamp":   int(time.time() * 1000),
                }
                asyncio.create_task(self._ws_client.send_now(frame))

    def _on_secondary(self) -> bool:
        """
        Returns True when the cursor is currently on a secondary device.
        Used by button/scroll/key forwarding to gate events: only forward
        when the cursor has moved onto a secondary screen.
        When there is no layout (session not started) or cursor is on our
        own screen, return False so events are not forwarded.
        """
        if not self._is_primary or not self._layout:
            # Non-primary agent always receives (injection path), never sends
            return False
        return bool(
            self._current_device_id
            and self._current_device_id != self._device_id
        )

    def _forward_mouse_button(self, button: int, action: str, x: int, y: int) -> None:
        """Mouse button events MUST NOT be dropped — send immediately.

        BLOCKER 3 FIX: only forward when cursor is on a secondary device.
        """
        if not self._ws_client:
            return
        if not self._on_secondary():
            return
        frame = {
            "version": 1, "type": f"mouse_{action}",
            "button": button, "x": x, "y": y,
            "timestamp": int(time.time() * 1000),
        }
        asyncio.create_task(self._ws_client.send_now(frame))

    def _forward_mouse_scroll(self, dx: int, dy: int) -> None:
        """BLOCKER 3 FIX: only forward when cursor is on a secondary device."""
        if not self._ws_client:
            return
        if not self._on_secondary():
            return
        frame = {"version": 1, "type": "mouse_scroll", "dx": dx, "dy": dy,
                  "timestamp": int(time.time() * 1000)}
        asyncio.create_task(self._ws_client.send_now(frame))

    def _forward_key(self, vk: int, scan: int, flags: int, action: str) -> None:
        """
        Keyboard events MUST preserve ordering and MUST NOT be dropped.
        SECURITY: vk and scan are NEVER logged — only forwarded over TLS.
        BLOCKER 3 FIX: only forward when cursor is on a secondary device.
        """
        if not self._ws_client:
            return
        if not self._on_secondary():
            return
        frame = {
            "version": 1, "type": f"key_{action}",
            "vk": vk, "scan": scan, "flags": flags,
            "timestamp": int(time.time() * 1000),
        }
        asyncio.create_task(self._ws_client.send_now(frame))

    # ── Input injection (SECONDARY device) ─────────────────────────────────

    def _inject_input(self, msg: dict) -> None:
        """
        Inject a received control frame as local OS input.
        SECURITY: never log msg contents (may contain vk/scan).
        """
        if sys.platform != "win32":
            return

        from agent.windows.input import (
            inject_mouse_move, inject_mouse_button,
            inject_mouse_scroll, inject_key,
        )

        mtype = msg.get("type", "")
        try:
            if mtype == "mouse_move":
                inject_mouse_move(int(msg["x"]), int(msg["y"]))
            elif mtype in ("mouse_down", "mouse_up"):
                action = "down" if mtype == "mouse_down" else "up"
                inject_mouse_button(int(msg.get("button", 0)), action)
            elif mtype == "mouse_scroll":
                inject_mouse_scroll(int(msg.get("dy", 0)))
            elif mtype in ("key_down", "key_up"):
                action = "down" if mtype == "key_down" else "up"
                inject_key(
                    int(msg["vk"]), int(msg["scan"]), int(msg.get("flags", 0)), action
                )
        except (KeyError, ValueError, TypeError):
            # Malformed frame — ignore silently (no logging of frame contents)
            pass

    def _warp_cursor(self, x: int, y: int) -> None:
        if sys.platform == "win32":
            from agent.windows.input import set_cursor_pos
            set_cursor_pos(x, y)

    # ── Display configuration ───────────────────────────────────────────────

    async def _report_display_config(self) -> None:
        if sys.platform == "win32" and self._ws_client:
            from agent.windows.input import enumerate_monitors, get_primary_screen_size
            try:
                monitors = enumerate_monitors()
                pw, ph = get_primary_screen_size()
                frame = {
                    "version":        1,
                    "type":           "display_config",
                    "monitors":       [m.to_dict() for m in monitors],
                    "primary_width":  pw,
                    "primary_height": ph,
                    "timestamp":      int(time.time() * 1000),
                }
                await self._ws_client.send(frame)
            except Exception as e:
                log.warning("display_config failed: %s", type(e).__name__)

    # ── Failsafe ────────────────────────────────────────────────────────────

    def _on_failsafe(self) -> None:
        """
        Called by the hook manager when Ctrl+Shift+Alt+F12 is pressed.
        MUST work WITHOUT network access — purely local.
        """
        _STATE_LOG.warning("FAILSAFE ACTIVATED — releasing all control immediately")
        self._release_control("local_failsafe_hotkey")

        # Best-effort: notify server (may fail if disconnected — that's OK)
        if self._ws_client:
            try:
                import asyncio as _asyncio
                _asyncio.create_task(self._ws_client.send_now({
                    "version":    1,
                    "type":       "session_stop",
                    "reason":     "local_failsafe",
                    "timestamp":  int(time.time() * 1000),
                }))
            except Exception:
                pass
