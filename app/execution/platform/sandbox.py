"""
ExecutionSandbox — Phase 3 of the Execution Platform.

Each execution receives its own isolated workspace.  The sandbox:

  - creates an isolated temp directory (outside the real workspace)
  - maintains isolated cache and logs subdirectories
  - enforces resource limits via subprocess preexec_fn (Linux only)
  - cleans itself up on exit (or on explicit cleanup() call)

The sandbox never modifies the original workspace.  All subprocess
cwd are pointed at the sandbox workspace.  Artifacts are collected
from the sandbox and moved to the artifact store.

Platform compatibility:
  - Temp directory: tempfile.gettempdir() — never /tmp hardcoded
  - Resource limits: Linux only via resource module — silently skipped
  - Directory creation: uses pathlib — works on Windows/macOS/Linux
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Resource limits (Linux only — silently skipped elsewhere)
_MAX_MEMORY_BYTES  = 512 * 1024 * 1024   # 512 MB
_MAX_PROCESSES     = 64
_MAX_FILE_SIZE     = 100 * 1024 * 1024   # 100 MB


def _apply_limits() -> None:
    """preexec_fn for spawned subprocesses (Linux only)."""
    if sys.platform != "linux":
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,   (_MAX_MEMORY_BYTES, _MAX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_NPROC, (_MAX_PROCESSES, _MAX_PROCESSES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_FILE_SIZE, _MAX_FILE_SIZE))
    except Exception:
        pass  # best-effort: never crash the subprocess before it starts


@dataclass
class SandboxPaths:
    """Resolved paths for one sandbox instance."""
    root: Path          # e.g. /tmp/executions/exec-abc123/
    workspace: Path     # root/workspace/   — symlinked from real project ws
    cache: Path         # root/cache/
    logs: Path          # root/logs/
    artifacts: Path     # root/artifacts/
    tmp: Path           # root/tmp/         — isolated tmp for this execution


class ExecutionSandbox:
    """
    Isolated execution environment for one project run.

    Usage:
        sandbox = ExecutionSandbox(real_workspace, execution_id)
        sandbox.create()
        try:
            # run inside sandbox.paths.workspace
            # logs go to sandbox.paths.logs
        finally:
            sandbox.cleanup()

    The sandbox workspace is a copy of the real project workspace.
    All subprocess commands run inside sandbox.paths.workspace.
    Cache, logs, and artifacts are isolated to sandbox.paths.*.
    """

    def __init__(self, real_workspace: Path, execution_id: str) -> None:
        self.real_workspace = real_workspace
        self.execution_id   = execution_id
        self._base_dir      = Path(tempfile.gettempdir()) / "executions"
        self._root          = self._base_dir / execution_id
        self.paths: Optional[SandboxPaths] = None
        self._created       = False

    def create(self) -> SandboxPaths:
        """
        Create the sandbox directory tree.
        Returns SandboxPaths with all resolved paths.
        Must be called before any subprocess is started.
        """
        root = self._root
        workspace = root / "workspace"
        cache     = root / "cache"
        logs      = root / "logs"
        artifacts = root / "artifacts"
        tmp       = root / "tmp"

        for d in (root, workspace, cache, logs, artifacts, tmp):
            d.mkdir(parents=True, exist_ok=True)

        # Copy real workspace contents into the sandbox workspace
        # We copy instead of symlink to ensure complete isolation
        if self.real_workspace.exists():
            try:
                _copy_workspace(self.real_workspace, workspace)
            except Exception as exc:
                log.warning(
                    "sandbox: could not copy workspace %s → %s: %s",
                    self.real_workspace, workspace, exc,
                )

        self.paths = SandboxPaths(
            root=root,
            workspace=workspace,
            cache=cache,
            logs=logs,
            artifacts=artifacts,
            tmp=tmp,
        )
        self._created = True
        log.info(
            "sandbox created: exec_id=%s root=%s ws=%s",
            self.execution_id, root, workspace,
        )
        return self.paths

    def cleanup(self) -> int:
        """
        Remove the entire sandbox root.
        Returns the number of bytes freed (approximate).
        """
        if not self._created or not self._root.exists():
            return 0
        freed = _dir_size(self._root)
        try:
            shutil.rmtree(self._root, ignore_errors=True)
            log.info("sandbox cleaned up: exec_id=%s freed=%d bytes",
                     self.execution_id, freed)
        except Exception as exc:
            log.warning("sandbox cleanup failed: %s", exc)
        self._created = False
        return freed

    @property
    def npm_env(self) -> dict:
        """
        Environment overrides that redirect all PM caches to the sandbox.
        Safe to pass as env= to any subprocess that touches npm/pnpm/yarn.
        """
        if not self.paths:
            raise RuntimeError("Sandbox not created — call create() first")
        cache_dir = str(self.paths.cache)
        tmp_dir   = str(self.paths.tmp)
        env = dict(os.environ)
        env["npm_config_cache"]    = cache_dir
        env["npm_config_logs_dir"] = str(self.paths.logs)
        env["NPM_CONFIG_CACHE"]    = cache_dir
        env["NPM_CONFIG_LOGS_DIR"] = str(self.paths.logs)
        env["PNPM_HOME"]           = os.path.join(cache_dir, "pnpm-home")
        env["TMPDIR"]              = tmp_dir       # used by some build tools
        env["TMP"]                 = tmp_dir
        env["TEMP"]                = tmp_dir
        return env

    def __repr__(self) -> str:
        return (
            f"ExecutionSandbox(execution_id={self.execution_id!r}, "
            f"created={self._created})"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_SKIP_DIRS  = frozenset({".git", "node_modules", "__pycache__", ".next",
                          "dist", "build", ".cache", ".venv", "venv"})
_SKIP_EXTS  = frozenset({".pyc", ".pyo", ".log"})
_MAX_COPY_MB = 50   # skip files over 50 MB


def _copy_workspace(src: Path, dst: Path) -> None:
    """Copy project source files into the sandbox workspace, skipping heavy artifacts."""
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        # Skip ignored directories
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        # Skip ignored extensions
        if item.is_file() and item.suffix.lower() in _SKIP_EXTS:
            continue
        # Skip very large files
        if item.is_file():
            try:
                if item.stat().st_size > _MAX_COPY_MB * 1024 * 1024:
                    log.debug("sandbox: skipping large file %s", item)
                    continue
            except Exception:
                continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(item, target)
            except Exception as exc:
                log.debug("sandbox: could not copy %s: %s", item, exc)


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total
