"""
Inventory collector — builds the `inventory_report` frame.

Platform readers are injected so the shaping logic is testable anywhere;
`collect_inventory()` wires in the real readers for the current platform.
Every reader is optional and failure-isolated: one failing reader leaves its
section empty instead of dropping the whole report.
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1

MAX_APPS = 500
MAX_DISKS = 26
MAX_PROCESSES = 20

_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def shape_apps(entries: Iterable[dict]) -> list[dict]:
    """Normalise raw app entries, drop duplicates, sort by name, cap at MAX_APPS."""
    seen: set[tuple[str, str]] = set()
    apps: list[dict] = []
    for entry in entries:
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        version = (entry.get("version") or "").strip()
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        size_mb = entry.get("size_mb")
        apps.append({
            "name": name[:200],
            "publisher": (entry.get("publisher") or "").strip()[:200] or None,
            "version": version[:64] or None,
            "size_mb": _round(size_mb) if isinstance(size_mb, (int, float)) and size_mb >= 0 else None,
        })
    apps.sort(key=lambda a: a["name"].lower())
    return apps[:MAX_APPS]


def shape_processes(entries: Iterable[tuple[str, int]]) -> list[dict]:
    """Aggregate (process name, rss bytes) by name; keep the largest MAX_PROCESSES."""
    totals: dict[str, int] = {}
    for name, rss in entries:
        if not name or not isinstance(rss, int) or rss < 0:
            continue
        totals[name] = totals.get(name, 0) + rss
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:MAX_PROCESSES]
    return [{"name": name[:120], "memory_mb": _round(rss / _MB)} for name, rss in ranked]


def _safe(reader: Optional[Callable], default):
    if reader is None:
        return default
    try:
        return reader()
    except Exception as e:  # a missing permission or API must not kill the report
        log.warning("inventory reader %s failed: %s", getattr(reader, "__name__", "?"), type(e).__name__)
        return default


def build_inventory_frame(
    *,
    apps_reader: Optional[Callable[[], Iterable[dict]]] = None,
    disks_reader: Optional[Callable[[], list[dict]]] = None,
    memory_reader: Optional[Callable[[], Optional[dict]]] = None,
    processes_reader: Optional[Callable[[], Iterable[tuple[str, int]]]] = None,
    recycle_bin_reader: Optional[Callable[[], Optional[dict]]] = None,
) -> dict:
    """Run the readers and return a protocol-v1 `inventory_report` frame."""
    return {
        "version": PROTOCOL_VERSION,
        "type": "inventory_report",
        "apps": shape_apps(_safe(apps_reader, [])),
        "disks": list(_safe(disks_reader, []))[:MAX_DISKS],
        "memory": _safe(memory_reader, None),
        "top_processes": shape_processes(_safe(processes_reader, [])),
        "recycle_bin": _safe(recycle_bin_reader, None),
        "timestamp": int(time.time() * 1000),
    }


# ── psutil-backed readers (cross-platform) ───────────────────────────────────

def read_disks() -> list[dict]:
    import psutil

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue  # e.g. an empty card reader slot
        disks.append({
            "mount": part.mountpoint[:16],
            "total_gb": _round(usage.total / _GB),
            "free_gb": _round(usage.free / _GB),
        })
    return disks


def read_memory() -> dict:
    import psutil

    vm = psutil.virtual_memory()
    return {"total_mb": _round(vm.total / _MB, 0), "used_mb": _round(vm.used / _MB, 0)}


def read_processes() -> list[tuple[str, int]]:
    import psutil

    result = []
    for proc in psutil.process_iter(["name", "memory_info"]):
        info = proc.info
        mem = info.get("memory_info")
        if info.get("name") and mem is not None:
            result.append((info["name"], int(mem.rss)))
    return result


def collect_inventory() -> dict:
    """Collect a snapshot of this device with the real platform readers."""
    apps_reader = recycle_bin_reader = None
    if sys.platform == "win32":
        from agent.inventory import windows

        apps_reader = windows.read_installed_apps
        recycle_bin_reader = windows.read_recycle_bin
    return build_inventory_frame(
        apps_reader=apps_reader,
        disks_reader=read_disks,
        memory_reader=read_memory,
        processes_reader=read_processes,
        recycle_bin_reader=recycle_bin_reader,
    )
