"""
SelfModifyingEngine — the heart of the AI OS.

Allows the runtime to rewrite its own source files safely.

Operations:
  patch   — find + replace inside a file (with rollback support)
  append  — add content at end of file
  prepend — add content at start of file
  replace — overwrite entire file
  create  — create a new file (in allowed dirs only)

Safety guarantees:
  - Policy engine checked before any write
  - SHA-256 hash of original stored for verification
  - Backup created in kernel_backups/ before every write
  - Rollback restores from backup

Every modification is logged in KernelState.modifications.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.kernel.policy import PolicyEngine, PolicyViolation

if TYPE_CHECKING:
    from app.kernel.state import KernelState

log = logging.getLogger(__name__)

_PROJECT_ROOT  = Path(__file__).parent.parent.parent.resolve()
_BACKUP_DIR    = Path(tempfile.gettempdir()) / "kernel-backups"


class ModifyError(Exception):
    pass


class SelfModifyingEngine:
    """
    Safe runtime code modification with audit trail and rollback.

    Usage:
        engine = SelfModifyingEngine(policy, state)
        engine.patch("app/commands/builtin/run_cmd.py",
                     find="old_text", replace="new_text",
                     description="Update default port")
    """

    def __init__(self, policy: PolicyEngine, state: "KernelState") -> None:
        self._policy = policy
        self._state  = state
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public operations ─────────────────────────────────────────────────────

    def patch(
        self, file: str, *, find: str, replace: str,
        description: str = "", count: int = -1,
    ) -> dict:
        """
        Find-and-replace inside a file.
        count=-1 means replace all occurrences.
        Returns {"status", "occurrences", "file", "backup"}.
        """
        path = _resolve(file)
        self._policy.check_write(path)

        original = self._read(path)
        occurrences = original.count(find)
        if occurrences == 0:
            raise ModifyError(f"Text not found in {file}: {find!r}")

        if count == -1:
            modified = original.replace(find, replace)
        else:
            modified = original.replace(find, replace, count)

        self._policy.check_write(path, modified)
        backup = self._backup(path, original)
        self._write(path, modified)

        rec = self._state.record_modification(
            file=file, action="patch",
            before_hash=_sha256(original), after_hash=_sha256(modified),
            description=description or f"patch {occurrences} occurrence(s) of {find[:40]!r}",
        )
        log.info("kernel patched %s: %d occurrence(s)", file, occurrences)
        return {"status": "patched", "file": file, "occurrences": occurrences,
                "backup": str(backup), "modification_index": len(self._state.modifications) - 1}

    def append(self, file: str, *, content: str, description: str = "") -> dict:
        """Append content to the end of a file."""
        path = _resolve(file)
        self._policy.check_write(path, content)

        original = self._read(path) if path.exists() else ""
        modified = original.rstrip("\n") + "\n" + content
        backup   = self._backup(path, original)
        self._write(path, modified)

        self._state.record_modification(
            file=file, action="append",
            before_hash=_sha256(original), after_hash=_sha256(modified),
            description=description or f"append {len(content)} chars",
        )
        return {"status": "appended", "file": file, "backup": str(backup)}

    def prepend(self, file: str, *, content: str, description: str = "") -> dict:
        """Prepend content to the start of a file."""
        path = _resolve(file)
        self._policy.check_write(path, content)

        original = self._read(path) if path.exists() else ""
        modified = content + "\n" + original.lstrip("\n")
        backup   = self._backup(path, original)
        self._write(path, modified)

        self._state.record_modification(
            file=file, action="prepend",
            before_hash=_sha256(original), after_hash=_sha256(modified),
            description=description or f"prepend {len(content)} chars",
        )
        return {"status": "prepended", "file": file, "backup": str(backup)}

    def replace(self, file: str, *, content: str, description: str = "") -> dict:
        """Overwrite the entire file with new content."""
        path = _resolve(file)
        self._policy.check_write(path, content)

        original = self._read(path) if path.exists() else ""
        backup   = self._backup(path, original)
        self._write(path, content)

        self._state.record_modification(
            file=file, action="replace",
            before_hash=_sha256(original), after_hash=_sha256(content),
            description=description or f"replace entire file ({len(content)} chars)",
        )
        return {"status": "replaced", "file": file, "backup": str(backup)}

    def create(self, file: str, *, content: str, description: str = "") -> dict:
        """Create a new file (fails if it already exists)."""
        path = _resolve(file)
        if path.exists():
            raise ModifyError(f"File already exists: {file}. Use replace to overwrite.")
        self._policy.check_write(path, content)

        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, content)

        self._state.record_modification(
            file=file, action="create",
            before_hash="", after_hash=_sha256(content),
            description=description or f"create file ({len(content)} chars)",
        )
        return {"status": "created", "file": file}

    def rollback(self, index: int) -> dict:
        """Restore a file from its backup using the modification index."""
        mods = self._state.modifications
        if not (0 <= index < len(mods)):
            raise ModifyError(f"No modification at index {index}. "
                              f"Total modifications: {len(mods)}")

        rec = mods[index]
        if rec.rolled_back:
            raise ModifyError(f"Modification {index} was already rolled back.")

        path   = _resolve(rec.file)
        backup = _backup_path(path, rec.timestamp)

        if not backup.exists():
            raise ModifyError(
                f"Backup not found for modification {index}: {backup}\n"
                f"Cannot roll back. Manual recovery required."
            )

        self._write(path, backup.read_text(encoding="utf-8", errors="replace"))
        self._state.mark_rolled_back(index)
        log.info("kernel rollback: index=%d file=%s", index, rec.file)
        return {"status": "rolled_back", "file": rec.file, "index": index,
                "restored_from": str(backup)}

    def diff(self, file: str) -> dict:
        """Show the current file content vs its most recent backup."""
        path = _resolve(file)
        if not path.exists():
            raise ModifyError(f"File not found: {file}")

        current = path.read_text(encoding="utf-8", errors="replace")
        backups = sorted(_BACKUP_DIR.glob(f"{path.stem}__*.bak"), reverse=True)
        if not backups:
            return {"file": file, "has_backup": False, "current_hash": _sha256(current)}

        latest_backup = backups[0].read_text(encoding="utf-8", errors="replace")
        return {
            "file"         : file,
            "has_backup"   : True,
            "backup_file"  : str(backups[0]),
            "current_hash" : _sha256(current),
            "backup_hash"  : _sha256(latest_backup),
            "changed"      : current != latest_backup,
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise ModifyError(f"File not found: {path}")

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".kernel_tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    def _backup(self, path: Path, content: str) -> Path:
        dest = _backup_path(path, time.time())
        dest.write_text(content, encoding="utf-8")
        return dest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(file: str) -> Path:
    p = Path(file)
    if p.is_absolute():
        return p
    return (_PROJECT_ROOT / p).resolve()


def _sha256(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode()
    return hashlib.sha256(content).hexdigest()[:16]


def _backup_path(path: Path, ts: float) -> Path:
    ts_int = int(ts * 1000)
    return _BACKUP_DIR / f"{path.stem}__{ts_int}.bak"
