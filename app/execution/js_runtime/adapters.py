"""
Runtime adapters — one per package manager.

Each adapter encapsulates everything the RuntimeManager needs to know
about a specific package manager: how to detect it, verify it, and
build install/run commands.

Adding a new runtime:
    1. Subclass AbstractRuntimeAdapter
    2. Add one detector: bun.lockb / pnpm-lock.yaml / etc.
    3. Register in ADAPTER_REGISTRY (bottom of file)
    Zero modifications to existing adapters required (Open/Closed).
"""
from __future__ import annotations

import logging
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional

log = logging.getLogger(__name__)


class AbstractRuntimeAdapter(ABC):
    """
    Contract every package manager adapter must satisfy.

    All methods are synchronous and side-effect-free (no subprocess I/O
    except verify(), which probes the binary exactly once per host).
    """

    # Unique identifier used in log messages and error reports.
    name: ClassVar[str]

    # Ordered list of lockfiles this PM produces. Used by the detector.
    lockfiles: ClassVar[tuple[str, ...]] = ()

    @property
    @abstractmethod
    def cmd(self) -> list[str]:
        """Base command (e.g. ["npm"] or ["node", "/path/npm-cli.js"])."""

    @abstractmethod
    def install_args(self) -> list[str]:
        """Full argv for installing dependencies (no script name)."""

    @abstractmethod
    def run_args(self, script: str) -> list[str]:
        """Full argv for executing a named script."""

    @abstractmethod
    def verify(self) -> bool:
        """
        Confirm the PM is functional on this host.
        Called at most once per adapter instance; callers cache the result.
        Must not raise — return False on any error.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} cmd={self.cmd}>"


# ── Concrete adapters ─────────────────────────────────────────────────────────

class NpmAdapter(AbstractRuntimeAdapter):
    name = "npm"
    lockfiles = ("package-lock.json",)

    @property
    def cmd(self) -> list[str]:
        return ["npm"]

    def install_args(self) -> list[str]:
        # No --prefer-offline: Render has no pre-existing npm cache.
        return ["npm", "install", "--ignore-scripts"]

    def run_args(self, script: str) -> list[str]:
        return ["npm", "run", script]

    def verify(self) -> bool:
        return _probe_exe("npm")


class PnpmAdapter(AbstractRuntimeAdapter):
    name = "pnpm"
    lockfiles = ("pnpm-lock.yaml",)

    @property
    def cmd(self) -> list[str]:
        return ["pnpm"]

    def install_args(self) -> list[str]:
        return ["pnpm", "install", "--ignore-scripts"]

    def run_args(self, script: str) -> list[str]:
        return ["pnpm", "run", script]

    def verify(self) -> bool:
        return _probe_exe("pnpm")


class YarnAdapter(AbstractRuntimeAdapter):
    name = "yarn"
    lockfiles = ("yarn.lock",)

    @property
    def cmd(self) -> list[str]:
        return ["yarn"]

    def install_args(self) -> list[str]:
        return ["yarn", "install", "--non-interactive", "--ignore-scripts"]

    def run_args(self, script: str) -> list[str]:
        # yarn 1 classic: yarn <script>  (no "run" keyword needed but works either way)
        return ["yarn", script]

    def verify(self) -> bool:
        return _probe_exe("yarn")


class BunAdapter(AbstractRuntimeAdapter):
    name = "bun"
    lockfiles = ("bun.lockb",)

    @property
    def cmd(self) -> list[str]:
        return ["bun"]

    def install_args(self) -> list[str]:
        return ["bun", "install"]

    def run_args(self, script: str) -> list[str]:
        return ["bun", "run", script]

    def verify(self) -> bool:
        return _probe_exe("bun")


class NpmCliJsFallbackAdapter(AbstractRuntimeAdapter):
    """
    Compatibility adapter for when the npm shell wrapper is broken.
    Invokes the underlying npm-cli.js directly through node.

    This is NOT the normal execution path — it is used only when
    NpmAdapter.verify() returns False and npm-cli.js is found on disk.
    """
    name = "npm-cli"
    lockfiles = ()  # not a lockfile-detected PM

    # Search paths for npm-cli.js across common Node.js install layouts.
    _SEARCH_PATHS: ClassVar[tuple[str, ...]] = (
        "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/share/npm/bin/npm-cli.js",
        "/opt/homebrew/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/local/share/.config/yarn/global/node_modules/npm/bin/npm-cli.js",
    )

    def __init__(self, cli_path: str) -> None:
        self._cli_path = cli_path

    @classmethod
    def find(cls) -> Optional["NpmCliJsFallbackAdapter"]:
        """Return an instance if npm-cli.js is present, else None."""
        for p in cls._SEARCH_PATHS:
            if os.path.isfile(p):
                log.debug("npm-cli.js fallback found at %s", p)
                return cls(p)
        return None

    @property
    def cmd(self) -> list[str]:
        return ["node", self._cli_path]

    def install_args(self) -> list[str]:
        return ["node", self._cli_path, "install", "--ignore-scripts"]

    def run_args(self, script: str) -> list[str]:
        return ["node", self._cli_path, "run", script]

    def verify(self) -> bool:
        return _probe_exe("node") and os.path.isfile(self._cli_path)


# ── Registry (ordered by priority for lockfile-less detection) ────────────────
#
# The order here determines probe order when no lockfile is found:
# bun > pnpm > yarn > npm  (faster tools first).
# NpmCliJsFallbackAdapter is NOT in this list — it's added dynamically.

ADAPTER_REGISTRY: tuple[type[AbstractRuntimeAdapter], ...] = (
    BunAdapter,
    PnpmAdapter,
    YarnAdapter,
    NpmAdapter,
)

# Lockfile → adapter class, built from registry.  Used by the detector.
LOCKFILE_MAP: dict[str, type[AbstractRuntimeAdapter]] = {
    lf: cls
    for cls in ADAPTER_REGISTRY
    for lf in cls.lockfiles
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _probe_exe(name: str) -> bool:
    """Return True if `name --version` exits 0, False on any failure."""
    try:
        r = subprocess.run(
            [name, "--version"],
            capture_output=True,
            timeout=5,
        )
        ok = r.returncode == 0
        if not ok:
            log.debug("_probe_exe: %s --version → exit %d", name, r.returncode)
        return ok
    except FileNotFoundError:
        log.debug("_probe_exe: %s not found", name)
        return False
    except subprocess.TimeoutExpired:
        log.warning("_probe_exe: %s --version timed out", name)
        return False
    except Exception as exc:
        log.warning("_probe_exe: %s unexpected error: %s", name, exc)
        return False
