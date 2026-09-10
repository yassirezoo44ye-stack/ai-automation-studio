"""
Flow Device Agent — Windows System Tray Icon

Shows agent status in the Windows system tray using pystray + Pillow.
The icon reflects the current agent state and lets the user stop remote
control or quit the agent entirely.

States shown:
  🔵 IDLE / CONNECTING   — "Flow Agent: Connecting…"
  🟢 CONNECTED           — "Flow Agent: Connected"
  🔴 CONTROL_ACTIVE      — "Flow: Remote Control ACTIVE"
  ⚫ REVOKED             — "Flow Agent: Device Revoked"

Tray menu items:
  - Status label (disabled — display only)
  - Stop Remote Control   (visible only when control is active)
  - ─────────────────────
  - Quit

Dependencies:
  pip install pystray pillow

Falls back gracefully if pystray/pillow are not installed
(logs a warning; agent continues without a tray icon).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

_TRAY_AVAILABLE = False
try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_AVAILABLE = True
except ImportError:
    pass


# ── Icon drawing ──────────────────────────────────────────────────────────────

_ICON_SIZE = 64

def _make_icon(color: tuple[int, int, int]) -> "Image.Image":
    """Draw a solid circle on a transparent background."""
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 6
    draw.ellipse(
        [margin, margin, _ICON_SIZE - margin, _ICON_SIZE - margin],
        fill=(*color, 255),
    )
    return img


_COLOR_CONNECTING     = (100, 120, 220)   # blue
_COLOR_CONNECTED      = (46,  204,  64)   # green
_COLOR_CONTROL_ACTIVE = (255,  65,  54)   # red (danger — control active)
_COLOR_REVOKED        = ( 80,  80,  80)   # grey


# ── Tray manager ──────────────────────────────────────────────────────────────

class FlowTrayIcon:
    """
    Manages the Windows system tray icon for the Flow Device Agent.

    Thread-safe: update_state() can be called from any thread.
    run() blocks the calling thread (must be run on a dedicated thread
    or in the main thread on Windows).
    """

    def __init__(
        self,
        on_stop_control: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._on_stop_control = on_stop_control
        self._on_quit         = on_quit

        self._state       = "connecting"
        self._icon        = None
        self._lock        = threading.Lock()

    def run(self) -> None:
        """
        Start the tray icon. Blocks until the icon is stopped.
        Call this on a dedicated daemon thread.
        """
        if not _TRAY_AVAILABLE:
            log.warning("pystray/pillow not installed — tray icon unavailable")
            return

        self._icon = pystray.Icon(
            name  = "FlowAgent",
            icon  = _make_icon(_COLOR_CONNECTING),
            title = "Flow Agent: Connecting…",
            menu  = self._build_menu(),
        )
        self._icon.run()

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def update_state(self, state: str) -> None:
        """
        Update the tray icon to reflect the new agent state.
        Safe to call from any thread.
        """
        if not _TRAY_AVAILABLE or not self._icon:
            return

        with self._lock:
            self._state = state

        color, title = self._state_visuals(state)

        try:
            self._icon.icon  = _make_icon(color)
            self._icon.title = title
            # Rebuild menu so "Stop Remote Control" shows/hides correctly
            self._icon.menu  = self._build_menu()
        except Exception as e:
            log.debug("tray update_state error: %s", type(e).__name__)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _state_visuals(self, state: str) -> tuple[tuple[int, int, int], str]:
        if state == "control_active":
            return _COLOR_CONTROL_ACTIVE, "Flow: Remote Control ACTIVE"
        if state == "connected":
            return _COLOR_CONNECTED, "Flow Agent: Connected"
        if state == "revoked":
            return _COLOR_REVOKED, "Flow Agent: Device Revoked"
        # idle / connecting / stopping / unknown
        return _COLOR_CONNECTING, "Flow Agent: Connecting…"

    def _build_menu(self) -> "pystray.Menu":
        if not _TRAY_AVAILABLE:
            return None

        _, title = self._state_visuals(self._state)
        items = [
            pystray.MenuItem(title, None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]

        if self._state == "control_active":
            items.append(
                pystray.MenuItem(
                    "Stop Remote Control",
                    lambda icon, item: self._on_stop_control(),
                )
            )
            items.append(pystray.Menu.SEPARATOR)

        items.append(
            pystray.MenuItem(
                "Quit",
                lambda icon, item: self._quit(),
            )
        )

        return pystray.Menu(*items)

    def _quit(self) -> None:
        self._on_quit()
        self.stop()


# ── Convenience factory ───────────────────────────────────────────────────────

def start_tray(
    on_stop_control: Callable[[], None],
    on_quit: Callable[[], None],
) -> FlowTrayIcon:
    """
    Create and start the tray icon on a daemon thread.
    Returns the FlowTrayIcon so the caller can call update_state() later.
    """
    tray = FlowTrayIcon(on_stop_control=on_stop_control, on_quit=on_quit)

    t = threading.Thread(target=tray.run, daemon=True, name="flow-tray")
    t.start()

    return tray
