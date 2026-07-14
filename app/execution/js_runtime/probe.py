"""
Runtime environment probes.

Two probe classes:

SystemProbe — full 14-field snapshot taken once before any execution.
    Covers OS, arch, user, CWD, HOME, PATH, TMPDIR, Node, Python,
    available PMs, writable dirs, cache dirs, disk free, memory free.

EnvironmentProbe — npm-focused legacy probe (kept for backward compat).
    Covers ~/.npm writability, npm cache dir, lockfile, versions.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── SystemProbe (Phase 1 full diagnostic) ─────────────────────────────────────

@dataclass
class SystemProbeResult:
    """
    Complete environmental snapshot — all 14 facts.

    Every field is populated (never None unless explicitly Optional).
    Used by Phase A to stream a diagnostic header before execution begins.
    """
    # Identity
    os_name: str            # "Linux 5.15.0"
    architecture: str       # "x86_64"
    current_user: str       # "render"

    # Filesystem
    working_dir: str        # "/tmp/projects/abc123"
    home: str               # "/home/render"
    path: str               # "/usr/local/bin:…"
    tmpdir: str             # "/tmp"

    # Runtimes
    node_version: Optional[str]   # "v20.11.0" | None
    python_version: str           # "3.11.2"

    # Package managers (all that responded to --version)
    available_pms: dict[str, str]       # {"npm": "10.2.4", "pnpm": "8.6.0"}

    # Filesystem writability
    writable_dirs: dict[str, bool]      # {"/tmp": True, "/home/render": False}

    # Cache paths that will be used
    cache_dirs: dict[str, str]          # {"npm": "/tmp/npm-cache", "pnpm": "…"}

    # Resources
    disk_free_mb: int           # -1 if unavailable
    memory_free_mb: Optional[int]   # None if platform doesn't expose it

    warnings: list[str] = field(default_factory=list)

    def as_log_lines(self) -> list[str]:
        """Human-readable lines for streaming to the client."""
        pm_str = "  ".join(
            f"{k} {v}" for k, v in self.available_pms.items()
        ) or "none found ⚠"

        writable_str = " | ".join(
            f"{Path(k).name or k}={'✓' if v else '✗'}"
            for k, v in self.writable_dirs.items()
        )

        mem_str = (
            f"{self.memory_free_mb} MB"
            if self.memory_free_mb is not None
            else "unavailable"
        )
        path_display = (
            self.path if len(self.path) <= 80 else self.path[:80] + "…"
        )

        lines = [
            "── Runtime Environment ───────────────────────────────────────",
            f"  OS              : {self.os_name}",
            f"  Architecture    : {self.architecture}",
            f"  User            : {self.current_user}",
            f"  Workspace       : {self.working_dir}",
            f"  HOME            : {self.home}",
            f"  TMPDIR          : {self.tmpdir}",
            f"  PATH            : {path_display}",
            f"  Node            : {self.node_version or 'NOT FOUND ⚠'}",
            f"  Python          : {self.python_version}",
            f"  Package Mgrs    : {pm_str}",
            f"  Writable        : {writable_str}",
        ]
        for name, path in self.cache_dirs.items():
            lines.append(f"  Cache ({name:<8}) : {path}")
        lines += [
            f"  Disk Free       : {self.disk_free_mb} MB"
            if self.disk_free_mb >= 0
            else "  Disk Free       : unavailable",
            f"  Memory Free     : {mem_str}",
        ]
        for w in self.warnings:
            lines.append(f"  ⚠ WARNING       : {w}")
        lines.append("─────────────────────────────────────────────────────────────")
        return lines


class SystemProbe:
    """
    Synchronous, side-effect-free full environment snapshot.

    Uses Python stdlib only for most fields.  Subprocess calls are
    limited to version probes (node --version, npm --version, etc.)
    with a 5-second timeout each.  Never raises — returns what it finds.
    """

    def probe(self, ws: Path) -> SystemProbeResult:
        warnings: list[str] = []
        tmpdir = tempfile.gettempdir()
        home = os.environ.get("HOME") or str(Path.home())

        # OS and architecture
        os_name = f"{platform.system()} {platform.release()}".strip()
        arch = platform.machine() or platform.processor() or "unknown"

        # Current user (try multiple env vars before os.getlogin)
        current_user = (
            os.environ.get("USER")
            or os.environ.get("USERNAME")
            or os.environ.get("LOGNAME")
            or _safe_getlogin()
            or "unknown"
        )

        # PATH
        path = os.environ.get("PATH", "")

        # Node version
        node_version = _run_ver(["node", "--version"])
        if not node_version:
            warnings.append("Node.js not found — JS projects cannot run")

        # Python version
        python_version = sys.version.split()[0]

        # All available package managers
        available_pms: dict[str, str] = {}
        for pm in ("npm", "pnpm", "yarn", "bun"):
            v = _run_ver([pm, "--version"])
            if v:
                available_pms[pm] = v
        if not available_pms:
            warnings.append(
                "No package manager found (npm/pnpm/yarn/bun) — "
                "dependency installation will fail"
            )

        # Writable directory check
        dirs_to_check = {tmpdir: False, home: False, str(ws): False}
        for d in list(dirs_to_check):
            dirs_to_check[d] = _is_writable(d)
        if not dirs_to_check.get(tmpdir, False):
            warnings.append(
                f"TMPDIR ({tmpdir}) is not writable — "
                "npm cache redirect will fail"
            )
        if not dirs_to_check.get(home, False):
            warnings.append(
                f"HOME ({home}) is not writable — "
                "npm may fail to write logs"
            )

        # Cache directories (platform-aware)
        npm_cache = os.path.join(tmpdir, "npm-cache")
        pnpm_home = os.path.join(tmpdir, "pnpm-home")
        cache_dirs: dict[str, str] = {"npm": npm_cache, "pnpm": pnpm_home}

        # Disk space
        try:
            usage = shutil.disk_usage(tmpdir)
            disk_free_mb = int(usage.free / 1024 / 1024)
            if disk_free_mb < 100:
                warnings.append(
                    f"Low disk space: only {disk_free_mb} MB free in {tmpdir}"
                )
        except Exception:
            disk_free_mb = -1

        # Memory (best-effort, never raises)
        memory_free_mb = _read_memory_free_mb()

        return SystemProbeResult(
            os_name=os_name,
            architecture=arch,
            current_user=current_user,
            working_dir=str(ws),
            home=home,
            path=path,
            tmpdir=tmpdir,
            node_version=node_version,
            python_version=python_version,
            available_pms=available_pms,
            writable_dirs=dirs_to_check,
            cache_dirs=cache_dirs,
            disk_free_mb=disk_free_mb,
            memory_free_mb=memory_free_mb,
            warnings=warnings,
        )


# ── EnvironmentProbe (npm-focused legacy probe) ───────────────────────────────

@dataclass
class ProbeResult:
    """Snapshot of the npm-focused runtime environment at probe time."""
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
    Collects evidence about the npm-specific runtime environment.
    Kept for backward compatibility with RuntimeManager.
    """

    def probe(self, ws: Path) -> ProbeResult:
        tmpdir = tempfile.gettempdir()
        home = os.environ.get("HOME") or str(Path.home())
        home_npm = Path(home) / ".npm"

        # Determine effective npm cache dir
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
        tmp_writable = _is_writable(tmpdir)
        home_npm_writable: Optional[bool] = None
        if home_npm.exists():
            home_npm_writable = _is_writable(str(home_npm))
            if not home_npm_writable:
                warnings.append(
                    f"{home_npm} exists but is NOT writable — "
                    "npm will fail to write logs"
                )
        elif not _is_writable(home):
            warnings.append(
                f"HOME ({home}) is not writable — "
                "npm cannot create .npm directory"
            )

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
            warnings.append(f"{tmpdir} is NOT writable — cannot use as fallback cache")

        # Lockfile detection
        lockfile_found: Optional[str] = None
        for lf in _LOCKFILE_PRIORITY:
            if (ws / lf).exists():
                lockfile_found = lf
                break

        # Node/npm versions
        node_version = _run_ver(["node", "--version"])
        npm_version = _run_npm_version()

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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_writable(path: str) -> bool:
    try:
        return os.access(path, os.W_OK)
    except Exception:
        return False


def _run_ver(cmd: list[str]) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.decode().strip()
    except Exception:
        pass
    return None


def _safe_getlogin() -> Optional[str]:
    try:
        return os.getlogin()
    except Exception:
        return None


def _run_npm_version() -> Optional[str]:
    """Try npm --version, then npm-cli.js paths."""
    v = _run_ver(["npm", "--version"])
    if v:
        return v
    for cli in (
        "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
        "/usr/lib/node_modules/npm/bin/npm-cli.js",
    ):
        if os.path.isfile(cli):
            v = _run_ver(["node", cli, "--version"])
            if v:
                return v + f" (via {cli})"
    return None


def _read_memory_free_mb() -> Optional[int]:
    """Return free memory in MB.  None if the platform doesn't expose it."""
    # Linux
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    # macOS (total only — estimate 40% free)
    try:
        r = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, timeout=3,
        )
        if r.returncode == 0:
            return int(r.stdout.strip()) * 40 // 100 // 1024 // 1024
    except Exception:
        pass
    # Windows
    try:
        r = subprocess.run(
            ["wmic", "OS", "get", "FreePhysicalMemory", "/Value"],
            capture_output=True, timeout=3,
        )
        if r.returncode == 0:
            for line in r.stdout.decode().splitlines():
                if "FreePhysicalMemory=" in line:
                    return int(line.split("=")[1].strip()) // 1024
    except Exception:
        pass
    return None
