"""
CommandContext — shared state passed to every command handler.

Carries the parsed invocation so handlers don't need to reparse.
Also exposes helpers that commands commonly need:
  - workspace resolution
  - project_id lookup
  - environment access
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class CommandContext:
    """
    Everything a command handler knows about its invocation.

    Created by CommandRunner for each execution.  Handlers receive
    this as their only argument and read from it — they never write back.
    """
    # Parsed from the raw input
    command: str
    args: list[str] = field(default_factory=list)
    flags: dict[str, str] = field(default_factory=dict)   # --key=value or --key value
    raw_input: str = ""

    # Resolved helpers
    workspace: Optional[Path] = None        # --workspace or first positional arg
    project_id: str = ""                    # --project or inferred from workspace
    execution_id: Optional[str] = None      # --execution (for status/report queries)

    # Caller identity (REST API enriches this)
    caller: str = "cli"                     # "cli" | "api" | "plugin"
    user_id: Optional[str] = None

    # Runtime state passthrough (for chained commands)
    runtime_state: dict[str, Any] = field(default_factory=dict)

    # ── Convenience accessors ─────────────────────────────────────────────────

    def first_arg(self, default: str = "") -> str:
        return self.args[0] if self.args else default

    def flag(self, key: str, default: str = "") -> str:
        return self.flags.get(key, self.flags.get(key.replace("-", "_"), default))

    def flag_bool(self, key: str) -> bool:
        v = self.flag(key)
        return v.lower() not in ("", "false", "0", "no") if v else key in self.flags

    def resolved_workspace(self) -> Optional[Path]:
        """Return the workspace path, resolved from --workspace, first arg, or CWD."""
        if self.workspace:
            return self.workspace
        if self.args:
            p = Path(self.args[0]).expanduser().resolve()
            if p.exists():
                return p
        return None
