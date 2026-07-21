"""
Plugin Compatibility Matrix — a read-only aggregation over data
PluginLoader.load() already persists (plugin_installations.manifest, the
full PluginManifest JSON each install stores). No new comparator, no new
state: reuses version_satisfies (app.marketplace.dependencies) and
PLATFORM_VERSION exactly as load() already checks them at install/upgrade
time — this exposes that same check queryably, for every installed
plugin at once, instead of only enforced one-at-a-time on load.

_evaluate_plugin_compatibility is split out as a pure function (plain
dicts in, plain dict out, no I/O) so its logic is directly unit-testable
without a database — build_compatibility_matrix is just the DB fetch
plus a map() over it.
"""
from __future__ import annotations

import uuid
from typing import Any


def _evaluate_plugin_compatibility(
    row: dict[str, Any], by_plugin_id: dict[str, dict[str, Any]], *, platform_version: str,
) -> dict[str, Any]:
    from app.marketplace.dependencies import version_satisfies

    manifest = row.get("manifest") or {}
    min_v = manifest.get("min_platform_version")
    max_v = manifest.get("max_platform_version")

    platform_compatible = True
    if min_v and not version_satisfies(platform_version, f">={min_v}"):
        platform_compatible = False
    if platform_compatible and max_v and not version_satisfies(platform_version, f"<={max_v}"):
        platform_compatible = False

    dependencies: list[dict[str, Any]] = []
    for dep in manifest.get("dependencies", []):
        dep_row = by_plugin_id.get(dep["plugin_id"])
        optional = dep.get("optional", False)
        if dep_row is None:
            installed_version, satisfied = None, optional
        else:
            installed_version = dep_row["version"]
            satisfied = (
                dep_row["status"] == "enabled"
                and version_satisfies(installed_version, dep["version_constraint"])
            )
        dependencies.append({
            "plugin_id": dep["plugin_id"],
            "version_constraint": dep["version_constraint"],
            "optional": optional,
            "installed_version": installed_version,
            "satisfied": satisfied,
        })

    return {
        "plugin_id": row["plugin_id"],
        "installed_version": row["version"],
        "status": row["status"],
        "platform_version": platform_version,
        "min_platform_version": min_v,
        "max_platform_version": max_v,
        "platform_compatible": platform_compatible,
        "dependencies": dependencies,
        "fully_compatible": platform_compatible and all(d["satisfied"] for d in dependencies),
    }


async def build_compatibility_matrix(org_id: str) -> list[dict[str, Any]]:
    from app.core.db import get_pool
    from app.plugins.loader import PLATFORM_VERSION, normalize_installation_row

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM plugin_installations WHERE organization_id=$1 ORDER BY plugin_id",
            uuid.UUID(org_id),
        )
    installed = [normalize_installation_row(dict(r)) for r in rows]
    by_plugin_id = {row["plugin_id"]: row for row in installed}
    return [
        _evaluate_plugin_compatibility(row, by_plugin_id, platform_version=PLATFORM_VERSION)
        for row in installed
    ]
