"""
EnvironmentProbe — collects direct evidence about the runtime environment.

Runs synchronously before any install attempt and returns structured
findings that are streamed to the client as diagnostic log lines.
No subprocess calls — pure filesystem and os.environ inspection.

This gives us evidence instead of assumptions when debugging
Render/Docker/Linux permission failures.
"""
from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProbeResult:
    """Snapshot of the runtime environment at probe time."""
    # Directories
    home: str
    cwd: str
    tmp_writable: bool
    home_npm_exists: bool
    home_npm_writable: Optional[bool]
    # npm config
    npm_config_cache: str
    npm_config_logs_dir: str
    cache_dir_writable: Optional[bool]
    # Workspace
    pkg_json_exists: bool
    lockfile_found: Optional[str]
    node_modules_exists: bool
    # Node binary
    node_version: Optional[str]
    npm_version: Optional[str]
    # Environment variables relevant to npm
    env_vars: dict[str, str]
    # Any warnings detected
    warnings: list[str] = field(default_factory=list)

    def as_log_lines(self) -> list[str]:
        """Return human-readable lines suitable for streaming to the client."""
        lines = [
            "── Runtime Environment Probe ──────────────────────────────",
            f"HOME             : {self.home}",
            f"CWD              : {self.cwd}",
            f"/tmp writable    : {self.tmp_writable}",
            f"~/.npm exists    : {self.home_npm_exists}",
            f"~/.npm writable  : {self.home_npm_writable}",
            f"npm cache dir    : {self.npm_config_cache}",
            f"npm logs dir     : {self.npm_config_logs_dir}",
            f"cache writable   : {self.cache_dir_writable}",
            f"package.json     : {self.pkg_json_exists}",
            f"lockfile         : {self.lockfile_found or 'none'}",
            f"node_modules     : {self.node_modules_exists}",
            f"node version     : {self.node_version or 'NOT FOUND'}",
            f"npm version      : {self.npm_version or 'NOT FOUND'}",
        ]
        for k, v in self.env_vars.items():
            lines.append(f"env {k:<20}: {v}")
        for w in self.warnings:
            lines.append(f"⚠ WARNING: {w}")
        lines.append("────────────────────────────────────────────────────────")
        return lines


_LOCKFILE_PRIORITY = ("bun.lockb", "pnpm-lock.yaml", "yarn.lock", "package-lock.json")
_NPM_ENV_KEYS = (
    "HOME", "USER", "PATH",
    "npm_config_cache", "npm_config_logs_dir", "npm_config_prefix",
    "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX",
    "PNPM_HOME", "NODE_PATH", "NODE_ENV",
)


class EnvironmentProbe:
    """
    Collects evidence about the runtime environment without making assumptions.

    Call probe() once before any install attempt.
    """

    def probe(self, ws: Path) -> ProbeResult:
        home = os.environ.get("HOME", os.path.expanduser("~"))
        home_npm = Path(home) / ".npm"

        # Determine effective npm cache dir
        # npm resolves: npm_config_cache env var > $HOME/.npm
        npm_cache = (
            os.environ.get("npm_config_cache")
            or os.environ.get("NPM_CONFIG_CACHE")
            or str(home_npm)
        )
        npm_logs = (
            os.environ.get("npm_config_logs_dir")
            or os.environ.get("NPM_CONFIG_LOGS_DIR")
            or str(Path(npm_cache) / "_logs")
        )

        warnings: list[str] = []

        # Writability checks
        tmp_writable = _is_writable("/tmp")
        home_npm_writable: Optional[bool] = None
        if home_npm.exists():
            home_npm_writable = _is_writable(str(home_npm))
            if not home_npm_writable:
                warnings.append(f"{home_npm} exists but is NOT writable — npm will fail to write logs")
        elif not _is_writable(home):
            warnings.append(f"HOME ({home}) is not writable — npm cannot create .npm directory")

        cache_dir_writable: Optional[bool] = None
        cache_path = Path(npm_cache)
        if cache_path.exists():
            cache_dir_writable = _is_writable(npm_cache)
            if not cache_dir_writable:
                warnings.append(f"npm cache dir {npm_cache} is NOT writable")
        else:
            parent = cache_path.parent
            if parent.exists():
                cache_dir_writable = _is_writable(str(parent))

        if not tmp_writable:
            warnings.append("/tmp is NOT writable — cannot use /tmp as fallback cache")

        # Lockfile detection
        lockfile_found: Optional[str] = None
        for lf in _LOCKFILE_PRIORITY:
            if (ws / lf).exists():
                lockfile_found = lf
                break

        # Node/npm versions (fast, no timeout issues)
        node_version = _run_version("node")
        npm_version = _run_version_via_cli()

        # Relevant env vars
        env_vars = {k: os.environ[k] for k in _NPM_ENV_KEYS if k in os.environ}

        return ProbeResult(
            home=home,
            cwd=str(ws),
            tmp_writable=tmp_writable,
            home_npm_exists=home_npm.exists(),
            home_npm_writable=home_npm_writable,
            npm_config_cache=npm_cache,
            npm_config_logs_dir=npm_logs,
            cache_dir_writable=cache_dir_writable,
            pkg_json_exists=(ws / "package.json").exists(),
            lockfile_found=lockfile_found,
            node_modules_exists=(ws / "node_modules").exists(),
            node_version=node_version,
            npm_version=npm_version,
            env_vars=env_vars,
            warnings=warnings,
        )


def _is_writable(path: str) -> bool:
    try:
        return os.access(path, os.W_OK)
    except Exception:
        return False


def _run_version(exe: str) -> Optional[str]:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.decode().strip()
    except Exception:
        pass
    return None


def _run_version_via_cli() -> Optional[str]:
    """Try npm --version, falling back to npm-cli.js paths."""
    v = _run_version("npm")
    if v:
        return v
    for cli in (
        "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/lib/node_modules/npm/bin/npm-cli.js",
    ):
        if os.path.isfile(cli):
            try:
                r = subprocess.run(["node", cli, "--version"], capture_output=True, timeout=5)
                if r.returncode == 0:
                    return r.stdout.decode().strip() + f" (via {cli})"
            except Exception:
                pass
    return None
