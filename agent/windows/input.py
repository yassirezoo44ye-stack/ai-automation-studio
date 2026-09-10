"""
Flow Device Agent — Windows Native Input Implementation

Uses Windows Low-Level Hooks (WH_MOUSE_LL, WH_KEYBOARD_LL) to capture
global mouse/keyboard input, and SendInput() to inject input on secondary devices.

Windows APIs used:
  - SetWindowsHookEx(WH_MOUSE_LL)   — global mouse hook (capture)
  - SetWindowsHookEx(WH_KEYBOARD_LL) — global keyboard hook (capture)
  - CallNextHookEx                   — pass events through (no suppression unless control_active)
  - SendInput                        — inject mouse/keyboard events on secondary agents
  - GetCursorPos / SetCursorPos      — cursor management
  - EnumDisplayMonitors              — detect all monitors
  - GetSystemMetrics                 — screen dimensions
  - GetMonitorInfo                   — per-monitor geometry

SECURITY:
  - Key codes (vk, scan) are NEVER logged, persisted, or included in exceptions.
  - Mouse coordinates are transient — only forwarded over TLS WebSocket.
  - No clipboard capture.
  - No screenshot capture.
  - No process inspection.

SUPPRESSION:
  - When CONTROL ACTIVE and this device is a secondary target, local mouse/
    keyboard input is suppressed (the primary machine drives this device).
  - When CONTROL ACTIVE and this device is the primary, local input is NOT
    suppressed — it is captured and forwarded.
  - When CONTROL INACTIVE, all input passes through normally.

FAILSAFE:
  - Emergency hotkey (Ctrl+Shift+Alt+F12) is processed BEFORE any suppression
    decision — it always releases hooks and signals the controller.
  - If the WebSocket disconnects, hooks are released immediately.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Never log actual key codes — this logger is intentionally silent about input
# payload values. Only log hook lifecycle events.
_INPUT_LOG = logging.getLogger(__name__ + ".lifecycle")

# ── Windows constants ─────────────────────────────────────────────────────────

WH_MOUSE_LL    = 14
WH_KEYBOARD_LL = 13

WM_MOUSEMOVE   = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP   = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP   = 0x0208
WM_MOUSEWHEEL  = 0x020A
WM_MOUSEHWHEEL = 0x020E

WM_KEYDOWN    = 0x0100
WM_KEYUP      = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP   = 0x0105

INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_SCANCODE    = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_MIDDLEDOWN  = 0x0020
MOUSEEVENTF_MIDDLEUP    = 0x0040
MOUSEEVENTF_WHEEL       = 0x0800
MOUSEEVENTF_HWHEEL      = 0x01000
MOUSEEVENTF_ABSOLUTE    = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

# Emergency failsafe hotkey: Ctrl+Shift+Alt+F12
VK_F12     = 0x7B
VK_CONTROL = 0x11
VK_SHIFT   = 0x10
VK_MENU    = 0x12   # Alt key

# ── ctypes structures ─────────────────────────────────────────────────────────

user32 = ctypes.windll.user32

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_ulong))


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",         ctypes.wintypes.POINT),
        ("mouseData",  ctypes.wintypes.DWORD),
        ("flags",      ctypes.wintypes.DWORD),
        ("time",       ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.wintypes.DWORD),
        ("scanCode",    ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.wintypes.DWORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("union", _INPUT_UNION)]


# ── Monitor enumeration ───────────────────────────────────────────────────────

class MonitorInfo:
    def __init__(self, x: int, y: int, width: int, height: int, primary: bool, name: str = ""):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.primary = primary
        self.name = name

    def to_dict(self) -> dict:
        return {
            "x":       self.x,
            "y":       self.y,
            "width":   self.width,
            "height":  self.height,
            "primary": self.primary,
            "name":    self.name,
        }


def enumerate_monitors() -> list[MonitorInfo]:
    """
    Enumerate all connected monitors.
    Returns screen geometry only — no desktop content captured.
    Handles negative coordinates (Windows virtual screen can start at negative x/y).
    """
    monitors = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize",    ctypes.wintypes.DWORD),
            ("rcMonitor", ctypes.wintypes.RECT),
            ("rcWork",    ctypes.wintypes.RECT),
            ("dwFlags",   ctypes.wintypes.DWORD),
        ]

    MONITORINFOF_PRIMARY = 1

    def _callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        rc = info.rcMonitor
        monitors.append(MonitorInfo(
            x=rc.left, y=rc.top,
            width=rc.right - rc.left,
            height=rc.bottom - rc.top,
            primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
        ))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_callback), 0)
    return monitors


def get_primary_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
    h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
    return w, h


def get_cursor_pos() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)


# ── Input injection (secondary device — receives control frames) ──────────────

def inject_mouse_move(x: int, y: int) -> None:
    """Move cursor to absolute screen coordinates on this device."""
    # Convert to normalized absolute coordinates (0..65535)
    w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if w <= 0 or h <= 0:
        return
    abs_x = int(x * 65535 / w)
    abs_y = int(y * 65535 / h)

    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = abs_x
    inp.union.mi.dy = abs_y
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def inject_mouse_button(button: int, action: str) -> None:
    """Inject a mouse button press/release. Coordinates not needed (uses current cursor pos)."""
    _button_flags = {
        (0, "down"): MOUSEEVENTF_LEFTDOWN,
        (0, "up"):   MOUSEEVENTF_LEFTUP,
        (1, "down"): MOUSEEVENTF_RIGHTDOWN,
        (1, "up"):   MOUSEEVENTF_RIGHTUP,
        (2, "down"): MOUSEEVENTF_MIDDLEDOWN,
        (2, "up"):   MOUSEEVENTF_MIDDLEUP,
    }
    flag = _button_flags.get((button, action))
    if flag is None:
        return
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dwFlags = flag
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def inject_mouse_scroll(dy: int) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.mouseData = ctypes.wintypes.DWORD(dy * 120)
    inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def inject_key(vk: int, scan: int, flags: int, action: str) -> None:
    """
    Inject a keyboard event on this device.
    SECURITY: vk and scan are hardware values only — never logged here.
    """
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.wScan = scan
    kflags = 0
    if action == "up":
        kflags |= KEYEVENTF_KEYUP
    if flags & KEYEVENTF_EXTENDEDKEY:
        kflags |= KEYEVENTF_EXTENDEDKEY
    inp.union.ki.dwFlags = kflags
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ── Hook manager (primary device — captures input) ────────────────────────────

class WindowsInputHookManager:
    """
    Installs low-level global mouse and keyboard hooks.

    When active (control_active=True):
      - Captures all mouse and keyboard input.
      - Calls the provided callbacks (on_mouse_*, on_key_*) with event data.
      - Suppresses local input processing (returns 1 from hook proc) when
        this device is a SECONDARY target receiving injected input.
      - NEVER suppresses input when this device is the primary controller.

    When inactive or on failsafe:
      - Releases all hooks immediately.
      - Local input passes through normally.
    """

    def __init__(
        self,
        on_mouse_move: Callable[[int, int], None],
        on_mouse_button: Callable[[int, str, int, int], None],
        on_mouse_scroll: Callable[[int, int], None],
        on_key: Callable[[int, int, int, str], None],
        on_failsafe: Callable[[], None],
        is_primary: bool = True,
    ):
        self._on_mouse_move = on_mouse_move
        self._on_mouse_button = on_mouse_button
        self._on_mouse_scroll = on_mouse_scroll
        self._on_key = on_key
        self._on_failsafe = on_failsafe
        self._is_primary = is_primary

        self._mouse_hook = None
        self._kb_hook = None
        self._mouse_proc = None
        self._kb_proc = None
        self._active = False
        self._key_seq = 0
        self._lock = threading.Lock()

    def install(self) -> None:
        """Install low-level hooks. Must be called from the message-pump thread."""
        if self._active:
            return

        self._mouse_proc = HOOKPROC(self._mouse_hook_proc)
        self._kb_proc    = HOOKPROC(self._kb_hook_proc)

        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, None, 0
        )
        self._kb_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kb_proc, None, 0
        )

        if not self._mouse_hook or not self._kb_hook:
            self.uninstall()
            raise RuntimeError("Failed to install Windows input hooks")

        self._active = True
        _INPUT_LOG.info("input hooks installed (primary=%s)", self._is_primary)

    def uninstall(self) -> None:
        """Release all hooks — safe to call multiple times."""
        with self._lock:
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
                self._mouse_hook = None
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
                self._kb_hook = None
            self._active = False
        _INPUT_LOG.info("input hooks released")

    @property
    def active(self) -> bool:
        return self._active

    def _is_failsafe_combo(self) -> bool:
        """Check if the emergency Ctrl+Shift+Alt+F12 combination is active."""
        def down(vk: int) -> bool:
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)
        return down(VK_CONTROL) and down(VK_SHIFT) and down(VK_MENU)

    def _mouse_hook_proc(self, nCode: int, wParam: int, lParam) -> int:
        if nCode < 0:
            return user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)

        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        x, y = ms.pt.x, ms.pt.y

        if wParam == WM_MOUSEMOVE:
            self._on_mouse_move(x, y)

        elif wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            btn_map = {
                WM_LBUTTONDOWN: 0, WM_RBUTTONDOWN: 1, WM_MBUTTONDOWN: 2,
            }
            self._on_mouse_button(btn_map[wParam], "down", x, y)

        elif wParam in (WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP):
            btn_map = {
                WM_LBUTTONUP: 0, WM_RBUTTONUP: 1, WM_MBUTTONUP: 2,
            }
            self._on_mouse_button(btn_map[wParam], "up", x, y)

        elif wParam == WM_MOUSEWHEEL:
            delta = ctypes.c_short(ms.mouseData >> 16).value
            self._on_mouse_scroll(0, delta)

        # When this device is a secondary (receiving forwarded input), suppress
        # local processing so injected events don't re-trigger the hook.
        # PRIMARY device: always pass through (never suppress own input).
        if not self._is_primary and self._active:
            return 1   # suppress

        return user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)

    def _kb_hook_proc(self, nCode: int, wParam: int, lParam) -> int:
        if nCode < 0:
            return user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        # NEVER log vk or scan values — they are hardware key identifiers
        vk    = kb.vkCode
        scan  = kb.scanCode
        flags = kb.flags

        # ── Emergency failsafe — highest priority ─────────────────────────
        if vk == VK_F12 and self._is_failsafe_combo():
            _INPUT_LOG.warning("FAILSAFE HOTKEY ACTIVATED — releasing control")
            # Don't call on_key; trigger failsafe callback instead.
            # The failsafe must NOT depend on the network.
            self.uninstall()
            try:
                self._on_failsafe()
            except Exception:
                pass
            return 1  # suppress this keypress from reaching any application

        action = "up" if wParam in (WM_KEYUP, WM_SYSKEYUP) else "down"

        with self._lock:
            self._key_seq += 1
            seq = self._key_seq

        # Call without logging vk/scan — the callback knows not to log them
        self._on_key(vk, scan, flags, action)

        # Secondary: suppress local processing of forwarded keystrokes
        if not self._is_primary and self._active:
            return 1  # suppress

        return user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)


def run_message_pump() -> None:
    """
    Windows message pump — required for hook proc delivery.
    Run this in a dedicated daemon thread.
    The pump exits when PostQuitMessage() is called or the thread is stopped.
    """
    from ctypes import wintypes

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd",    wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam",  wintypes.WPARAM),
            ("lParam",  wintypes.LPARAM),
            ("time",    wintypes.DWORD),
            ("pt",      wintypes.POINT),
        ]

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
