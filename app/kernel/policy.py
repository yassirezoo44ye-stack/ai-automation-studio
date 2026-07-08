"""
Policy Engine — controls what the self-modifying engine is allowed to do.

Prevents:
  - Modification of security-critical files
  - Writing outside the project root
  - Deletion of migration files, secrets, CI config
  - Path traversal attacks

Allows:
  - Modification of app code (app/, src/)
  - Plugin files (plugins/, commands/)
  - Config files (non-secret)
  - New file creation inside allowed dirs

Policy violation → PolicyViolation exception.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Protected path fragments — any match → denied ────────────────────────────
_PROTECTED_PATTERNS: tuple[str, ...] = (
    ".env",
    ".git/",
    "migrations/",
    "alembic/",
    "secrets",
    ".pem",
    ".key",
    ".p12",
    "id_rsa",
    "id_ed25519",
    ".github/workflows",
    "Dockerfile.prod",
    "render.yaml",
)

# ── Allowed write directories (relative to project root) ─────────────────────
_ALLOWED_WRITE_DIRS: tuple[str, ...] = (
    "app/",
    "src/",
    "plugins/",
    "commands/",
    "tests/",
    "app/commands/",
    "app/kernel/",
)

# ── Maximum file size that may be written (bytes) ────────────────────────────
_MAX_WRITE_BYTES = 512 * 1024   # 512 KB

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class PolicyViolation(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PolicyEngine:
    """
    Evaluates modification requests against the policy rules.

    Call check_write(path, content) before any file modification.
    Call check_read(path) before reading sensitive files.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = (project_root or _PROJECT_ROOT).resolve()

    # ── Public API ────────────────────────────────────────────────────────────

    def check_write(self, path: Path, content: str | bytes = "") -> None:
        """Raise PolicyViolation if writing path with content is forbidden."""
        resolved = self._resolve(path)
        self._check_traversal(resolved)
        self._check_protected(resolved)
        self._check_allowed_dir(resolved)
        if isinstance(content, str):
            content = content.encode()
        if len(content) > _MAX_WRITE_BYTES:
            raise PolicyViolation(
                f"Content too large: {len(content)} bytes > {_MAX_WRITE_BYTES} byte limit."
            )

    def check_read(self, path: Path) -> None:
        """Raise PolicyViolation if reading path is forbidden."""
        resolved = self._resolve(path)
        self._check_traversal(resolved)
        self._check_protected(resolved)

    def is_allowed_write(self, path: Path) -> bool:
        """Non-raising version of check_write."""
        try:
            self.check_write(path)
            return True
        except PolicyViolation:
            return False

    # ── Internal checks ───────────────────────────────────────────────────────

    def _resolve(self, path: Path) -> Path:
        try:
            return path.expanduser().resolve()
        except Exception:
            return path

    def _check_traversal(self, resolved: Path) -> None:
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise PolicyViolation(
                f"Path traversal denied: {resolved} is outside project root {self._root}"
            )

    def _check_protected(self, resolved: Path) -> None:
        path_str = str(resolved).replace("\\", "/")
        for pattern in _PROTECTED_PATTERNS:
            if pattern in path_str:
                raise PolicyViolation(
                    f"Protected path: '{pattern}' matched in {resolved}. "
                    f"This file cannot be modified by the kernel."
                )

    def _check_allowed_dir(self, resolved: Path) -> None:
        rel = str(resolved.relative_to(self._root)).replace("\\", "/")
        if not any(rel.startswith(d) for d in _ALLOWED_WRITE_DIRS):
            raise PolicyViolation(
                f"Write outside allowed directories: {rel}\n"
                f"Allowed: {', '.join(_ALLOWED_WRITE_DIRS)}"
            )
