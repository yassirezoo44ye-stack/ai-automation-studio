"""
Windows inventory readers — installed applications and Recycle Bin size.

Read-only: uses winreg queries and SHQueryRecycleBinW, nothing else.
`parse_uninstall_entry` is pure so it can be tested off Windows.
"""
from __future__ import annotations

import ctypes
from typing import Optional

# Installed-program lists Windows' own "Apps & features" is built from.
_UNINSTALL_PATHS = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
)

_VALUE_NAMES = (
    "DisplayName", "Publisher", "DisplayVersion", "EstimatedSize",
    "SystemComponent", "ParentKeyName", "ReleaseType",
)


def parse_uninstall_entry(values: dict) -> Optional[dict]:
    """Turn one Uninstall registry key's values into an app entry, or None to skip it.

    Skips what "Apps & features" hides: entries without a DisplayName, system
    components, and updates/hotfixes attached to a parent program.
    """
    name = values.get("DisplayName")
    if not isinstance(name, str) or not name.strip():
        return None
    if values.get("SystemComponent") == 1:
        return None
    if values.get("ParentKeyName"):
        return None
    if values.get("ReleaseType") in ("Update", "Hotfix", "Security Update"):
        return None
    size_kb = values.get("EstimatedSize")
    return {
        "name": name.strip(),
        "publisher": values.get("Publisher") if isinstance(values.get("Publisher"), str) else None,
        "version": values.get("DisplayVersion") if isinstance(values.get("DisplayVersion"), str) else None,
        "size_mb": size_kb / 1024 if isinstance(size_kb, int) and size_kb > 0 else None,
    }


def read_installed_apps() -> list[dict]:
    import winreg

    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    apps: list[dict] = []
    for hive_name, path in _UNINSTALL_PATHS:
        try:
            root = winreg.OpenKey(hives[hive_name], path)
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for i in range(count):
                try:
                    sub_name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, sub_name) as sub:
                        values = {}
                        for value_name in _VALUE_NAMES:
                            try:
                                values[value_name] = winreg.QueryValueEx(sub, value_name)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                entry = parse_uninstall_entry(values)
                if entry is not None:
                    apps.append(entry)
    return apps


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


def read_recycle_bin() -> dict:
    """Total size and item count across all drives' Recycle Bins."""
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
    hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))  # type: ignore[attr-defined]
    if hr != 0:
        raise OSError(f"SHQueryRecycleBinW failed: {hr:#x}")
    return {
        "items": int(info.i64NumItems),
        "size_mb": round(info.i64Size / (1024 * 1024), 1),
    }
