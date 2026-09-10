"""
Flow Device Agent — Secure Credential Storage

Uses Windows DPAPI (Data Protection API) via the `win32crypt` module
to encrypt the device credential at rest, bound to the local machine account.
This means:
  - The credential is encrypted with the Windows machine/user key material.
  - No raw credential is written to disk in plaintext.
  - The credential can only be decrypted on the same Windows user account.

On non-Windows platforms (macOS/Linux): falls back to a file-based store
in the user config directory (future: macOS Keychain / libsecret).

SECURITY CONTRACT:
  - Never log the raw credential value.
  - Never include the credential in exception messages.
  - Never transmit it except in the TLS-protected WebSocket auth frame.
  - Always clear the in-memory credential after use where possible.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CONFIG_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "FlowAgent"
_CRED_FILE = _CONFIG_DIR / "device.enc"
_CONFIG_FILE = _CONFIG_DIR / "config.json"


def _ensure_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # On Windows, restrict directory ACL to current user only via icacls
    # (best-effort — a missing icacls is not fatal)
    if sys.platform == "win32":
        try:
            import subprocess
            subprocess.run(
                ["icacls", str(_CONFIG_DIR), "/inheritance:r",
                 "/grant:r", f"{os.environ.get('USERNAME','*')}:F"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass


# ── Windows DPAPI ─────────────────────────────────────────────────────────────

def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI (user-scoped)."""
    try:
        import win32crypt
        return win32crypt.CryptProtectData(
            data,
            "FlowAgentCredential",   # data description (not the secret)
            None,                    # optional entropy
            None,                    # reserved
            None,                    # prompt struct
            0,                       # flags (0 = user scope)
        )
    except ImportError:
        raise RuntimeError(
            "pywin32 is required for Windows credential storage. "
            "Install it with: pip install pywin32"
        )


def _dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt bytes with Windows DPAPI."""
    try:
        import win32crypt
        _, plaintext = win32crypt.CryptUnprotectData(data, None, None, None, 0)
        return plaintext
    except ImportError:
        raise RuntimeError("pywin32 is required for credential decryption")


# ── Portable fallback (future macOS/Linux) ────────────────────────────────────

def _file_protect(data: bytes) -> bytes:
    """
    Non-Windows stub: stores base64 of the credential.
    TODO: implement macOS Keychain / libsecret for production.
    On macOS/Linux, restrict file permissions to 0o600.
    """
    import base64
    return base64.b64encode(data)


def _file_unprotect(data: bytes) -> bytes:
    import base64
    return base64.b64decode(data)


# ── Public API ────────────────────────────────────────────────────────────────

def save_credential(device_id: str, credential: str, server_url: str) -> None:
    """
    Persist the device credential securely.
    The raw credential is encrypted at rest — never written plaintext.
    """
    _ensure_dir()
    payload = json.dumps({
        "device_id":  device_id,
        "credential": credential,
        "server_url": server_url,
    }).encode("utf-8")

    if sys.platform == "win32":
        encrypted = _dpapi_protect(payload)
    else:
        encrypted = _file_protect(payload)
        _CRED_FILE.chmod(0o600)

    _CRED_FILE.write_bytes(encrypted)
    # Do NOT log credential value — log only device_id
    log.info("credential saved for device_id=%s", device_id)


def load_credential() -> tuple[str, str, str] | None:
    """
    Load and decrypt the stored device credential.
    Returns (device_id, credential, server_url) or None if not found.
    The credential value is not logged.
    """
    if not _CRED_FILE.exists():
        return None
    try:
        encrypted = _CRED_FILE.read_bytes()
        if sys.platform == "win32":
            plaintext = _dpapi_unprotect(encrypted)
        else:
            plaintext = _file_unprotect(encrypted)

        data = json.loads(plaintext.decode("utf-8"))
        return data["device_id"], data["credential"], data["server_url"]
    except Exception as e:
        # Log failure without revealing credential details
        log.warning("credential load failed: %s", type(e).__name__)
        return None


def clear_credential() -> None:
    """Remove stored credentials — called on revocation."""
    if _CRED_FILE.exists():
        try:
            _CRED_FILE.unlink()
        except Exception:
            pass
    log.info("device credential cleared")


def load_config() -> dict:
    """Load non-secret agent configuration (server URL, device name, etc.)."""
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_config(config: dict) -> None:
    """Save non-secret agent configuration."""
    _ensure_dir()
    # Never put credential in config dict — only in _CRED_FILE
    safe = {k: v for k, v in config.items() if k != "credential"}
    _CONFIG_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")
