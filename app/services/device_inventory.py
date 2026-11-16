"""
Device inventory snapshots — device advisor, M1 (read-only).

Opted-in Flow Device Agents send an `inventory_report` frame (installed apps,
disks, memory, largest processes, Recycle Bin size). The frame is untrusted
input: `sanitize_inventory` keeps only the known fields, with type checks and
size caps, before anything is stored. App and process names are data shown
to the user, never instructions.
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any, Optional

from app.core.db import get_pool

MAX_APPS = 500
MAX_DISKS = 26
MAX_PROCESSES = 20
SNAPSHOTS_KEPT = 30
# A reconnecting agent re-sends on every connect; ignore reports closer than this.
MIN_REPORT_INTERVAL_S = 5 * 60


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _number(value: Any, upper: float = 1e12) -> Optional[float]:
    # bool is an int subclass — reject it explicitly
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or value > upper:
        return None
    return round(float(value), 1)


def _list(value: Any, limit: int) -> list:
    return value[:limit] if isinstance(value, list) else []


def sanitize_inventory(msg: dict) -> dict:
    """Return a clean, fixed-shape copy of an `inventory_report` frame."""
    apps = []
    for item in _list(msg.get("apps"), MAX_APPS):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 200)
        if name is None:
            continue
        apps.append({
            "name": name,
            "publisher": _text(item.get("publisher"), 200),
            "version": _text(item.get("version"), 64),
            "size_mb": _number(item.get("size_mb")),
        })

    disks = []
    for item in _list(msg.get("disks"), MAX_DISKS):
        if not isinstance(item, dict):
            continue
        mount = _text(item.get("mount"), 16)
        total, free = _number(item.get("total_gb")), _number(item.get("free_gb"))
        if mount is None or total is None or free is None or free > total:
            continue
        disks.append({"mount": mount, "total_gb": total, "free_gb": free})

    processes = []
    for item in _list(msg.get("top_processes"), MAX_PROCESSES):
        if not isinstance(item, dict):
            continue
        name, memory = _text(item.get("name"), 120), _number(item.get("memory_mb"))
        if name is not None and memory is not None:
            processes.append({"name": name, "memory_mb": memory})

    memory = None
    raw_memory = msg.get("memory")
    if isinstance(raw_memory, dict):
        total, used = _number(raw_memory.get("total_mb")), _number(raw_memory.get("used_mb"))
        if total is not None and used is not None and used <= total:
            memory = {"total_mb": total, "used_mb": used}

    recycle_bin = None
    raw_bin = msg.get("recycle_bin")
    if isinstance(raw_bin, dict):
        items, size = _number(raw_bin.get("items")), _number(raw_bin.get("size_mb"))
        if items is not None and size is not None:
            recycle_bin = {"items": int(items), "size_mb": size}

    return {
        "apps": apps,
        "disks": disks,
        "memory": memory,
        "top_processes": processes,
        "recycle_bin": recycle_bin,
    }


async def record_inventory_snapshot(device_id: str, org_id: str, msg: dict) -> bool:
    """Store a sanitized snapshot; keep the newest SNAPSHOTS_KEPT per device.

    Returns False when the report was skipped because the previous one is too recent.
    """
    inventory = sanitize_inventory(msg)
    dev, org = uuid.UUID(device_id), uuid.UUID(org_id)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            recent = await conn.fetchval(
                """
                SELECT 1 FROM device_inventory_snapshots
                WHERE device_id = $1 AND organization_id = $2
                  AND collected_at > NOW() - make_interval(secs => $3)
                LIMIT 1
                """,
                dev, org, float(MIN_REPORT_INTERVAL_S),
            )
            if recent:
                return False
            await conn.execute(
                """
                INSERT INTO device_inventory_snapshots (device_id, organization_id, inventory)
                VALUES ($1, $2, $3::jsonb)
                """,
                dev, org, json.dumps(inventory),
            )
            await conn.execute(
                """
                DELETE FROM device_inventory_snapshots
                WHERE device_id = $1 AND organization_id = $2 AND id NOT IN (
                    SELECT id FROM device_inventory_snapshots
                    WHERE device_id = $1 AND organization_id = $2
                    ORDER BY collected_at DESC
                    LIMIT $3
                )
                """,
                dev, org, SNAPSHOTS_KEPT,
            )
    return True


async def get_latest_inventory(org_id: str, device_id: str) -> Optional[dict]:
    """Newest snapshot for a device in this organization, or None."""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT collected_at, inventory
            FROM device_inventory_snapshots
            WHERE device_id = $1 AND organization_id = $2
            ORDER BY collected_at DESC
            LIMIT 1
            """,
            uuid.UUID(device_id),
            uuid.UUID(org_id),
        )
    if row is None:
        return None
    inventory = row["inventory"]
    if isinstance(inventory, str):
        inventory = json.loads(inventory)
    return {"collected_at": row["collected_at"].isoformat(), "inventory": inventory}
