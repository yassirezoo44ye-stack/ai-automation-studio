"""
Flow Device Agent — Entry Point

Usage:
  # First-time enrollment (generates and stores credentials):
  python -m agent enroll --server wss://flow.example.com --name "My PC"

  # Normal operation (loads stored credentials and connects):
  python -m agent run

  # Revoke and clear local credentials:
  python -m agent clear

  # Show version:
  python -m agent version

  # Register agent to start on Windows login (packaged .exe only):
  python -m agent startup <install_path>

  # Remove Windows autostart registration:
  python -m agent remove-startup

Environment variables (override stored config):
  FLOW_SERVER_URL   — WebSocket server URL (wss://...)
  FLOW_DEVICE_ID    — Device UUID (overrides stored)
  FLOW_CREDENTIAL   — Raw credential (NOT RECOMMENDED — use enrollment instead)

SECURITY NOTES:
  - Credentials are stored using Windows DPAPI (never plaintext)
  - Raw credentials are never logged
  - Failsafe hotkey: Ctrl+Shift+Alt+F12 releases all hooks locally
  - Autostart uses HKCU (user scope) — no administrator privileges required
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# ── Logging ────────────────────────────────────────────────────────────────────
# Never log at DEBUG in production — hook callbacks may receive vk/scan codes.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("flow.agent")


# ── Argument parsing ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flow-agent",
        description="Flow Device Agent — multi-device control",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # run
    run_p = sub.add_parser("run", help="Start the agent (uses stored credentials)")
    run_p.add_argument("--no-tray", action="store_true", help="Disable system tray icon")

    # enroll
    enroll_p = sub.add_parser("enroll", help="Enroll this device with a Flow server")
    enroll_p.add_argument("--server",    required=True, help="Server URL (wss://...)")
    enroll_p.add_argument("--token",     required=True, help="Enrollment token (from Flow web UI)")
    enroll_p.add_argument("--name",      default="",    help="Display name for this device")
    enroll_p.add_argument("--platform",  default="windows")
    enroll_p.add_argument("--no-tray",   action="store_true")

    # clear
    sub.add_parser("clear", help="Revoke and clear stored device credentials")

    # version
    sub.add_parser("version", help="Print agent version")

    # startup — register HKCU autostart (Gate K.2)
    startup_p = sub.add_parser(
        "startup",
        help="Register agent to start on Windows login (HKCU, no UAC required)",
    )
    startup_p.add_argument(
        "install_path",
        help="Directory containing flow-agent.exe (e.g. %%LOCALAPPDATA%%\\FlowAgent\\app)",
    )

    # remove-startup — remove HKCU autostart (Gate K.2)
    sub.add_parser(
        "remove-startup",
        help="Remove Windows autostart registration",
    )

    return p


# ── Commands ───────────────────────────────────────────────────────────────────

async def cmd_enroll(args: argparse.Namespace) -> int:
    """
    Consume an enrollment token and store the resulting credential.
    The token is single-use and expires after 24 h.
    """
    import platform as _platform
    from agent.security.credentials import save_credential, save_config

    server = args.server.rstrip("/")
    # Use HTTP(S) for the enrollment REST call (not WS)
    http_base = server.replace("wss://", "https://").replace("ws://", "http://")
    enroll_url = f"{http_base}/api/devices/enroll"

    log.info("enrolling with server %s", http_base)

    try:
        import aiohttp
    except ImportError:
        log.error("aiohttp is required for enrollment: pip install aiohttp")
        return 1

    payload = {
        "enrollment_token": args.token,
        "device_name":      args.name or _platform.node(),
        "platform":         args.platform,
        "hostname":         _platform.node(),
        "agent_version":    _get_version(),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(enroll_url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                log.error("enrollment failed status=%d body=%s", resp.status, text[:200])
                return 1
            data = await resp.json()

    device_id  = data["device_id"]
    credential = data["credential"]   # raw — store immediately, don't log

    save_credential(device_id, credential, server)
    save_config({"device_name": args.name or _platform.node(), "server_url": server})

    log.info("enrollment SUCCESS device_id=%s", device_id)
    print(f"\n✅ Device enrolled successfully!\n   Device ID: {device_id}")
    print("   Credentials stored securely. Run `python -m agent run` to start.\n")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    """Load stored credentials and run the agent."""
    from agent.security.credentials import load_credential, load_config
    from agent.core.controller import DeviceAgentController

    # Allow environment-variable overrides (for testing / CI)
    env_server     = os.environ.get("FLOW_SERVER_URL")
    env_device_id  = os.environ.get("FLOW_DEVICE_ID")
    env_credential = os.environ.get("FLOW_CREDENTIAL")

    if env_device_id and env_credential and env_server:
        device_id  = env_device_id
        credential = env_credential
        server_url = env_server
        device_name = os.environ.get("FLOW_DEVICE_NAME", "")
    else:
        stored = load_credential()
        if stored is None:
            log.error(
                "no credentials found — run `python -m agent enroll` first"
            )
            return 1
        device_id, credential, server_url = stored
        cfg = load_config()
        device_name = cfg.get("device_name", "")

    log.info("starting agent device_id=%s server=%s", device_id, server_url)

    # Optional tray icon
    tray = None
    if not getattr(args, "no_tray", False) and sys.platform == "win32":
        try:
            from agent.windows.tray import start_tray
            tray = start_tray(
                on_stop_control=lambda: None,  # wired below after controller is ready
                on_quit=lambda: os._exit(0),
            )
        except Exception as e:
            log.debug("tray init failed: %s", type(e).__name__)

    def _on_state(state: str) -> None:
        log.info("agent state → %s", state)
        if tray:
            tray.update_state(state)

    controller = DeviceAgentController(
        device_id       = device_id,
        credential      = credential,
        server_url      = server_url,
        device_name     = device_name,
        on_state_change = _on_state,
    )

    # Wire tray stop-control button
    if tray:
        tray._on_stop_control = lambda: controller.stop()

    try:
        await controller.run()
    except KeyboardInterrupt:
        log.info("interrupted — stopping")
        controller.stop()

    # Security: zero out credential from memory after use
    credential = "0" * len(credential)
    del credential

    return 0


def cmd_clear() -> int:
    from agent.security.credentials import clear_credential
    clear_credential()
    print("✅ Credentials cleared.")
    return 0


def cmd_version() -> int:
    print(f"Flow Device Agent {_get_version()}")
    return 0


# ── Windows autostart (Gate K.2) ──────────────────────────────────────────────
# Uses HKCU\Software\Microsoft\Windows\CurrentVersion\Run — no UAC required.
# winreg is stdlib on Windows; on non-Windows this command is rejected early.

_AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_REG_KEY  = "FlowAgent"


def cmd_startup(args: argparse.Namespace) -> int:
    """
    Register the agent to start on Windows login.

    Writes:
      HKCU\\...\\Run\\FlowAgent = "<install_path>\\flow-agent.exe" run

    The executable is quoted so paths with spaces are handled correctly.
    No administrator privileges required (HKCU scope).
    """
    if sys.platform != "win32":
        print("autostart is only supported on Windows.")
        return 1

    import winreg
    from pathlib import Path

    install_path = Path(args.install_path).resolve()
    exe_path = install_path / "flow-agent.exe"
    # Quote the path in case it contains spaces; 'run' is the subcommand
    reg_value = f'"{exe_path}" run'

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _AUTOSTART_REG_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, _AUTOSTART_REG_KEY, 0, winreg.REG_SZ, reg_value)
    except OSError as e:
        log.error("could not write autostart registry key: %s", e)
        return 1

    print(f"✅ Flow Agent will start on login.")
    print(f"   Registry: HKCU\\...\\Run\\{_AUTOSTART_REG_KEY}")
    print(f"   Value:    {reg_value}")
    return 0


def cmd_remove_startup() -> int:
    """
    Remove the Windows autostart registration.

    Deletes HKCU\\...\\Run\\FlowAgent if it exists.
    No administrator privileges required (HKCU scope).
    """
    if sys.platform != "win32":
        print("autostart is only supported on Windows.")
        return 1

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _AUTOSTART_REG_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, _AUTOSTART_REG_KEY)
        print(f"✅ Autostart removed (HKCU\\...\\Run\\{_AUTOSTART_REG_KEY} deleted).")
    except FileNotFoundError:
        print(f"ℹ️  No autostart entry found (HKCU\\...\\Run\\{_AUTOSTART_REG_KEY}).")
    except OSError as e:
        log.error("could not remove autostart registry key: %s", e)
        return 1

    return 0


# ── Version ────────────────────────────────────────────────────────────────────

def _get_version() -> str:
    try:
        from agent.core.controller import AGENT_VERSION
        return AGENT_VERSION
    except ImportError:
        return "1.0.0"


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.command == "version":
        sys.exit(cmd_version())

    if args.command == "clear":
        sys.exit(cmd_clear())

    if args.command == "enroll":
        sys.exit(asyncio.run(cmd_enroll(args)))

    if args.command == "run":
        sys.exit(asyncio.run(cmd_run(args)))

    if args.command == "startup":
        sys.exit(cmd_startup(args))

    if args.command == "remove-startup":
        sys.exit(cmd_remove_startup())

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
