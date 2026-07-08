"""
KernelState — persistent in-process state for the AI Kernel.

Survives across command invocations within the same process.
Optionally persisted to disk (state.json) for cross-restart continuity.

Stores:
  - boot_time        : when the kernel started
  - command_count    : total commands executed
  - last_command     : last executed command name
  - modifications    : audit log of self-modifications
  - hot_reloads      : list of modules hot-reloaded
  - custom           : arbitrary user/plugin key-value store
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_STATE_FILE = Path(tempfile.gettempdir()) / "ai-kernel-state.json"


@dataclass
class ModificationRecord:
    """Audit trail for a single self-modification."""
    timestamp: float
    file: str
    action: str          # "patch" | "append" | "prepend" | "replace" | "create"
    before_hash: str
    after_hash: str
    description: str
    rolled_back: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp"  : round(self.timestamp, 3),
            "file"       : self.file,
            "action"     : self.action,
            "before_hash": self.before_hash,
            "after_hash" : self.after_hash,
            "description": self.description,
            "rolled_back": self.rolled_back,
        }


class KernelState:
    """
    Mutable kernel state — shared across all kernel components.
    One instance per process.
    """

    def __init__(self) -> None:
        self.boot_time     : float = time.time()
        self.command_count : int   = 0
        self.last_command  : str   = ""
        self.modifications : list[ModificationRecord] = []
        self.hot_reloads   : list[dict] = []
        self.custom        : dict[str, Any] = {}
        self._load()

    # ── Command tracking ──────────────────────────────────────────────────────

    def record_command(self, name: str) -> None:
        self.command_count += 1
        self.last_command   = name

    # ── Modification audit ────────────────────────────────────────────────────

    def record_modification(
        self, file: str, action: str,
        before_hash: str, after_hash: str,
        description: str,
    ) -> ModificationRecord:
        rec = ModificationRecord(
            timestamp   = time.time(),
            file        = file,
            action      = action,
            before_hash = before_hash,
            after_hash  = after_hash,
            description = description,
        )
        self.modifications.append(rec)
        self._save()
        return rec

    def mark_rolled_back(self, index: int) -> None:
        if 0 <= index < len(self.modifications):
            self.modifications[index].rolled_back = True
            self._save()

    # ── Hot-reload tracking ───────────────────────────────────────────────────

    def record_reload(self, module: str, trigger: str) -> None:
        self.hot_reloads.append({
            "timestamp": round(time.time(), 3),
            "module"   : module,
            "trigger"  : trigger,
        })
        self._save()

    # ── Custom store ──────────────────────────────────────────────────────────

    def set(self, key: str, value: Any) -> None:
        self.custom[key] = value
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        return self.custom.get(key, default)

    # ── Introspection ─────────────────────────────────────────────────────────

    def uptime_s(self) -> float:
        return round(time.time() - self.boot_time, 1)

    def to_dict(self) -> dict:
        return {
            "boot_time"    : round(self.boot_time, 3),
            "uptime_s"     : self.uptime_s(),
            "command_count": self.command_count,
            "last_command" : self.last_command,
            "modifications": [m.to_dict() for m in self.modifications],
            "hot_reloads"  : self.hot_reloads,
            "custom"       : self.custom,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_dict(), indent=2))
            tmp.replace(_STATE_FILE)
        except Exception as exc:
            log.debug("state save failed: %s", exc)

    def _load(self) -> None:
        if not _STATE_FILE.exists():
            return
        try:
            data = json.loads(_STATE_FILE.read_text())
            self.custom = data.get("custom", {})
            for m in data.get("modifications", []):
                rec = ModificationRecord(**m)
                self.modifications.append(rec)
        except Exception as exc:
            log.debug("state load failed: %s", exc)
