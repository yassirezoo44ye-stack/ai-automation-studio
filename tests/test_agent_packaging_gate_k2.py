"""
Gate K.2 — Windows Agent Packaging Tests

Tests what can be verified without a real Windows installation or
a live Flow server connection:

  K2-1   Parser accepts all expected subcommands
  K2-2   startup / remove-startup subcommands exist in parser
  K2-3   _build_parser() is free of import-time Windows-only deps
  K2-4   flow_agent.spec exists and is valid Python syntax
  K2-5   build.py exists and is valid Python syntax
  K2-6   install.bat / uninstall.bat contain expected strings
  K2-7   cmd_startup writes the correct HKCU registry value (mock)
  K2-8   cmd_remove_startup deletes the correct registry value (mock)
  K2-9   cmd_remove_startup handles missing key gracefully (mock)
  K2-10  startup refuses on non-Windows platforms gracefully
  K2-11  remove-startup refuses on non-Windows platforms gracefully
  K2-12  DPAPI credential path unchanged (regression guard)
  K2-13  No credentials or secrets in spec/build/install files

NOT tested here (requires real hardware / Windows environment):
  - PyInstaller build output (run: py -3.11 agent/build/build.py)
  - flow-agent.exe version / enroll / run
  - DPAPI encrypt/decrypt round-trip (needs pywin32 + Windows session)
  - WH_MOUSE_LL / WH_KEYBOARD_LL hooks in packaged exe
  - Tray icon rendering
  - End-to-end enroll → run → control → failsafe
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

_ROOT  = Path(__file__).resolve().parent.parent
_AGENT = _ROOT / "agent"
_BUILD = _AGENT / "build"


# ── K2-1  Parser subcommands ───────────────────────────────────────────────────

def test_parser_all_subcommands():
    """All expected subcommands must be accepted by _build_parser()."""
    from agent.__main__ import _build_parser
    parser = _build_parser()

    accepted = [
        ["run"],
        ["run", "--no-tray"],
        ["enroll", "--server", "wss://x.example.com", "--token", "tok"],
        ["enroll", "--server", "wss://x", "--token", "t", "--name", "PC"],
        ["clear"],
        ["version"],
        ["startup", r"C:\FlowAgent\app"],
        ["remove-startup"],
    ]
    for argv in accepted:
        ns = parser.parse_args(argv)
        assert ns.command == argv[0].replace("-", "_") or ns.command == argv[0]


# ── K2-2  startup / remove-startup in parser ──────────────────────────────────

def test_parser_startup_command():
    from agent.__main__ import _build_parser
    parser = _build_parser()
    ns = parser.parse_args(["startup", r"C:\Users\Me\FlowAgent\app"])
    assert ns.command == "startup"
    assert ns.install_path == r"C:\Users\Me\FlowAgent\app"


def test_parser_remove_startup_command():
    from agent.__main__ import _build_parser
    parser = _build_parser()
    ns = parser.parse_args(["remove-startup"])
    assert ns.command == "remove-startup"


# ── K2-3  No Windows-only imports at module level ──────────────────────────────

def test_no_windows_only_imports_at_module_level():
    """
    agent/__main__.py must be importable without win32crypt / pywin32.
    Windows-specific imports (winreg, win32crypt) are inside functions.
    """
    import agent.__main__  # noqa: F401 — test that import does not raise
    assert True


# ── K2-4  flow_agent.spec is valid Python ─────────────────────────────────────

def test_spec_file_exists():
    assert (_BUILD / "flow_agent.spec").exists(), \
        "agent/build/flow_agent.spec not found"


def test_spec_file_is_valid_python():
    src = (_BUILD / "flow_agent.spec").read_text(encoding="utf-8")
    # PyInstaller spec files are Python — they must parse cleanly.
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"flow_agent.spec has a syntax error: {e}")


def test_spec_contains_required_hiddenimports():
    src = (_BUILD / "flow_agent.spec").read_text(encoding="utf-8")
    for required in [
        "win32crypt",
        "pystray",
        "PIL._imaging",
        "websockets",
        "aiohttp",
        "agent.core.controller",
        "agent.windows.input",
        "agent.security.credentials",
        "winreg",
    ]:
        assert required in src, \
            f"flow_agent.spec is missing hiddenimport: {required!r}"


def test_spec_console_is_false():
    """Tray app must not open a console window."""
    src = (_BUILD / "flow_agent.spec").read_text(encoding="utf-8")
    assert "console=False" in src, \
        "flow_agent.spec must have console=False (tray application)"


# ── K2-5  build.py is valid Python ────────────────────────────────────────────

def test_build_py_exists():
    assert (_BUILD / "build.py").exists(), "agent/build/build.py not found"


def test_build_py_is_valid_python():
    src = (_BUILD / "build.py").read_text(encoding="utf-8")
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"build.py has a syntax error: {e}")


# ── K2-6  install.bat / uninstall.bat sanity ──────────────────────────────────

def test_install_bat_exists():
    assert (_BUILD / "install.bat").exists(), "agent/build/install.bat not found"


def test_uninstall_bat_exists():
    assert (_BUILD / "uninstall.bat").exists(), "agent/build/uninstall.bat not found"


def test_install_bat_references_exe():
    text = (_BUILD / "install.bat").read_text(encoding="utf-8", errors="replace")
    assert "flow-agent.exe" in text
    assert "LOCALAPPDATA" in text


def test_uninstall_bat_calls_clear():
    text = (_BUILD / "uninstall.bat").read_text(encoding="utf-8", errors="replace")
    assert "clear" in text
    assert "remove-startup" in text
    assert "LOCALAPPDATA" in text


def test_install_bat_no_hardcoded_server_url():
    """install.bat must NOT contain a hardcoded wss:// production URL."""
    text = (_BUILD / "install.bat").read_text(encoding="utf-8", errors="replace")
    # Placeholders like YOUR-FLOW-SERVER are fine; real hostnames are not
    import re
    real_wss = re.findall(r'wss://[a-z0-9][-a-z0-9.]+\.[a-z]{2,}', text, re.IGNORECASE)
    assert not real_wss, f"install.bat contains hardcoded WSS URL(s): {real_wss}"


# ── K2-7  cmd_startup writes the correct registry value ───────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="winreg only on Windows")
def test_cmd_startup_writes_registry():
    from agent.__main__ import cmd_startup, _AUTOSTART_REG_KEY
    import winreg

    args = argparse.Namespace(install_path=r"C:\test\FlowAgent\app")

    mock_key = MagicMock()
    with patch("winreg.OpenKey", return_value=mock_key.__enter__.return_value) as mock_open, \
         patch("winreg.SetValueEx") as mock_set:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        rc = cmd_startup(args)

    assert rc == 0
    mock_set.assert_called_once()
    _, name, _, vtype, value = mock_set.call_args[0]
    assert name == _AUTOSTART_REG_KEY
    assert vtype == winreg.REG_SZ
    assert "flow-agent.exe" in value
    assert "run" in value
    # Path must be quoted
    assert value.startswith('"')


@pytest.mark.skipif(sys.platform != "win32", reason="winreg only on Windows")
def test_cmd_startup_value_contains_install_path():
    from agent.__main__ import cmd_startup

    install = r"C:\Users\Test User\FlowAgent\app"   # path with space
    args = argparse.Namespace(install_path=install)

    captured = {}

    def _fake_set(key, name, reserved, vtype, value):
        captured["value"] = value

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)

    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.SetValueEx", side_effect=_fake_set):
        rc = cmd_startup(args)

    assert rc == 0
    # The installed path must appear in the registry value, quoted
    assert "FlowAgent" in captured["value"]
    assert captured["value"].startswith('"')


# ── K2-8  cmd_remove_startup deletes the correct key ─────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="winreg only on Windows")
def test_cmd_remove_startup_deletes_key():
    from agent.__main__ import cmd_remove_startup, _AUTOSTART_REG_KEY

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)

    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.DeleteValue") as mock_del:
        rc = cmd_remove_startup()

    assert rc == 0
    mock_del.assert_called_once()
    assert mock_del.call_args[0][1] == _AUTOSTART_REG_KEY


# ── K2-9  cmd_remove_startup handles missing key gracefully ───────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="winreg only on Windows")
def test_cmd_remove_startup_missing_key_is_not_an_error():
    from agent.__main__ import cmd_remove_startup

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)

    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.DeleteValue", side_effect=FileNotFoundError):
        rc = cmd_remove_startup()

    # FileNotFoundError (key absent) must return 0, not 1
    assert rc == 0


# ── K2-10 / K2-11  Platform guard on non-Windows ──────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="tests non-Windows path")
def test_cmd_startup_rejects_non_windows(capsys):
    from agent.__main__ import cmd_startup
    args = argparse.Namespace(install_path="/some/path")
    rc = cmd_startup(args)
    assert rc == 1
    out = capsys.readouterr().out
    assert "Windows" in out


@pytest.mark.skipif(sys.platform == "win32", reason="tests non-Windows path")
def test_cmd_remove_startup_rejects_non_windows(capsys):
    from agent.__main__ import cmd_remove_startup
    rc = cmd_remove_startup()
    assert rc == 1
    out = capsys.readouterr().out
    assert "Windows" in out


# ── K2-12  DPAPI credential path unchanged ────────────────────────────────────

def test_dpapi_credential_path():
    """Regression guard: DPAPI path must still be %APPDATA%/FlowAgent/device.enc."""
    from agent.security.credentials import _CRED_FILE, _CONFIG_DIR
    assert _CONFIG_DIR.name == "FlowAgent"
    assert _CRED_FILE.name == "device.enc"
    assert _CRED_FILE.parent == _CONFIG_DIR


def test_dpapi_config_path():
    from agent.security.credentials import _CONFIG_FILE, _CONFIG_DIR
    assert _CONFIG_FILE.name == "config.json"
    assert _CONFIG_FILE.parent == _CONFIG_DIR


# ── K2-13  No credentials/secrets in build files ──────────────────────────────

def test_no_hardcoded_credentials_in_build_files():
    """
    Build infrastructure files must not contain plaintext credentials,
    production secrets, or hardcoded server URLs.
    """
    import re
    build_files = list(_BUILD.glob("*"))
    build_files.append(_AGENT / "__main__.py")

    violations: list[str] = []
    for f in build_files:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            text_lower = text.lower()
        except Exception:
            continue

        # (1) Real WSS production URLs (not placeholders like *.example.com,
        #     YOUR-SERVER, or localhost)
        wss_matches = re.findall(
            r'wss://[a-z0-9][-a-z0-9.]+\.[a-z]{2,}',
            text,
            re.IGNORECASE,
        )
        real_wss = [
            m for m in wss_matches
            if ".example.com" not in m.lower()
            and "your-" not in m.lower()
            and "localhost" not in m.lower()
        ]
        if real_wss:
            violations.append(f"{f.name}: hardcoded WSS URL(s): {real_wss}")

        # (2) Raw private key material
        if "BEGIN PRIVATE KEY" in text or "BEGIN RSA PRIVATE KEY" in text:
            violations.append(f"{f.name}: contains private key material")

        # (3) postgres:// connection strings (hardcoded DB credentials)
        if "postgres://" in text_lower:
            violations.append(f"{f.name}: contains postgres:// connection string")

    assert not violations, f"Potential secrets in build files: {violations}"


# ── K2-14  AGENT_VERSION is defined ───────────────────────────────────────────

def test_agent_version_defined():
    from agent.core.controller import AGENT_VERSION
    assert isinstance(AGENT_VERSION, str)
    assert len(AGENT_VERSION) > 0
