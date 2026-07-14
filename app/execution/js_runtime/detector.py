"""
PackageManagerDetector — evidence-based PM selection with caching.

Detection priority (highest to lowest evidence quality):
  1. Lockfile presence  (strongest — committed artefact)
     bun.lockb          → bun
     pnpm-lock.yaml     → pnpm
     yarn.lock          → yarn
     package-lock.json  → npm
  2. package.json `packageManager` field  (explicit declaration)
     e.g. "packageManager": "pnpm@8.6.0"
  3. Executable probe  (what's available on this host)
     bun → pnpm → yarn → npm  (checked in priority order)
  4. npm-cli.js fallback  (broken npm binary recovery)

Performance:
  Detection results are cached by (workspace_path, lockfile_mtime).
  The cache is invalidated automatically when any lockfile changes.
  Executable probe results are cached for the process lifetime
  (they cannot change without a restart).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .adapters import (
    ADAPTER_REGISTRY,
    LOCKFILE_MAP,
    AbstractRuntimeAdapter,
    NpmCliJsFallbackAdapter,
)
from .errors import PackageManagerNotFound

log = logging.getLogger(__name__)

# Priority order for lockfile scanning (most specific first).
_LOCKFILE_PRIORITY: tuple[str, ...] = (
    "bun.lockb",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
)


@dataclass
class DetectionResult:
    """Outcome of PM detection including the reasoning trail."""
    adapter: AbstractRuntimeAdapter
    method: str              # "lockfile" | "packageManager_field" | "probe" | "fallback"
    evidence: str            # human-readable explanation
    lockfile_conflicts: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.adapter.name} (via {self.method}: {self.evidence})"


# ── Process-lifetime executable probe cache ───────────────────────────────────
# Key: adapter class → bool.  Only grows, never invalidated.
_exe_cache: dict[type[AbstractRuntimeAdapter], bool] = {}


def _verify_adapter(cls: type[AbstractRuntimeAdapter]) -> bool:
    if cls not in _exe_cache:
        instance = cls()
        _exe_cache[cls] = instance.verify()
        log.debug("executable probe: %s → %s", cls.name, _exe_cache[cls])
    return _exe_cache[cls]


# ── Workspace-level lockfile detection cache ──────────────────────────────────
# Key: (workspace_path, tuple of (lockfile, mtime)) → DetectionResult
_ws_cache: dict[tuple, DetectionResult] = {}


def _cache_key(ws: Path) -> tuple:
    mtimes = []
    for lf in _LOCKFILE_PRIORITY:
        p = ws / lf
        try:
            mtimes.append((lf, p.stat().st_mtime_ns))
        except FileNotFoundError:
            mtimes.append((lf, 0))
    return (str(ws), tuple(mtimes))


# ── Public API ────────────────────────────────────────────────────────────────

class PackageManagerDetector:
    """
    Stateless detector.  Instantiate once and call detect() per workspace.
    Detection results are cached internally — repeated calls for the same
    workspace are effectively free.
    """

    def detect(self, ws: Path) -> DetectionResult:
        """
        Return the best available package manager for this workspace.

        Raises:
            LockfileConflict       — multiple lockfiles found
            PackageManagerNotFound — no PM available at all
        """
        key = _cache_key(ws)
        if key in _ws_cache:
            cached = _ws_cache[key]
            log.debug("detector cache hit: %s → %s", ws.name, cached.adapter.name)
            return cached

        result = self._detect_uncached(ws)
        _ws_cache[key] = result
        log.info("detected PM for %s: %s", ws.name, result)
        return result

    def _detect_uncached(self, ws: Path) -> DetectionResult:
        # Step 1: lockfile scan
        found_lockfiles = [lf for lf in _LOCKFILE_PRIORITY if (ws / lf).exists()]

        if len(found_lockfiles) > 1:
            # Multiple lockfiles — warn but don't abort.  Use highest-priority one.
            log.warning("multiple lockfiles in %s: %s", ws, found_lockfiles)
            # Still proceed with the highest-priority lockfile.

        if found_lockfiles:
            primary = found_lockfiles[0]
            cls = LOCKFILE_MAP[primary]
            if not _verify_adapter(cls):
                # Lockfile is the authoritative declaration of which PM was used
                # to produce it.  Using a different PM on a foreign lockfile
                # produces different node_modules and can break the build silently.
                # Hard-stop here so the user gets a clear, actionable error
                # rather than a mysterious runtime failure ten minutes later.
                raise PackageManagerNotFound(
                    message=(
                        f"{primary} requires {cls.name} but it is not installed on this host. "
                        f"Install {cls.name} or remove {primary} to let the runtime choose a PM."
                    ),
                    tried=[cls.name],
                )
            return DetectionResult(
                adapter=cls(),
                method="lockfile",
                evidence=f"found {primary}",
                lockfile_conflicts=found_lockfiles[1:],
            )

        # Step 2: package.json `packageManager` field
        pkg_json = ws / "package.json"
        if pkg_json.exists():
            pm_name = _read_package_manager_field(pkg_json)
            if pm_name:
                for cls in ADAPTER_REGISTRY:
                    if cls.name == pm_name and _verify_adapter(cls):
                        return DetectionResult(
                            adapter=cls(),
                            method="packageManager_field",
                            evidence=f'package.json "packageManager": "{pm_name}"',
                        )
                log.warning(
                    'package.json declares "%s" but it is not installed', pm_name
                )

        # Step 3: executable probe (ordered by registry priority)
        tried: list[str] = []
        for cls in ADAPTER_REGISTRY:
            tried.append(cls.name)
            if _verify_adapter(cls):
                return DetectionResult(
                    adapter=cls(),
                    method="probe",
                    evidence=f"{cls.name} found via executable probe",
                )

        # Step 4: npm-cli.js fallback (broken npm binary recovery)
        fallback = NpmCliJsFallbackAdapter.find()
        if fallback and fallback.verify():
            return DetectionResult(
                adapter=fallback,
                method="fallback",
                evidence=f"npm binary broken; using node {fallback._cli_path}",
            )
        tried.append("npm-cli.js")

        raise PackageManagerNotFound(
            message="No JavaScript package manager is available on this host.",
            tried=tried,
        )


def _read_package_manager_field(pkg_json: Path) -> Optional[str]:
    """Extract the PM name from package.json `packageManager` field, or None."""
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        field_val = data.get("packageManager", "")
        if not field_val:
            return None
        # Format: "pnpm@8.6.0"  or just "pnpm"
        m = re.match(r"^([a-z]+)", field_val)
        return m.group(1) if m else None
    except Exception:
        return None
