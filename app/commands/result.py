"""
CommandResult — structured output from any command invocation.

Every command returns a CommandResult.  The CommandRunner serialises
it to JSON for the REST API and prints it for the CLI.

Fields:
    success     — bool
    command     — the command name that produced this result
    output      — primary human-readable output (may be multi-line)
    data        — structured payload (command-specific dict)
    error       — error message if success is False
    error_code  — machine-readable error code
    suggestions — actionable suggestions (on error: nearby commands)
    duration_ms — wall-clock time of the command execution
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CommandResult:
    success: bool
    command: str = ""
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""
    suggestions: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def ok(cls, command: str, output: str = "", data: dict | None = None) -> "CommandResult":
        return cls(success=True, command=command, output=output, data=data or {})

    @classmethod
    def fail(
        cls,
        command: str,
        error: str,
        error_code: str = "COMMAND_FAILED",
        suggestions: list[str] | None = None,
    ) -> "CommandResult":
        return cls(
            success=False, command=command, error=error,
            error_code=error_code, suggestions=suggestions or [],
        )

    @classmethod
    def unknown(cls, name: str, available: list[str]) -> "CommandResult":
        close = _closest(name, available)
        suggestions = [f"Did you mean: {c}?" for c in close[:3]] if close else []
        suggestions.append(f"Run 'help' to see all {len(available)} available commands.")
        return cls(
            success=False,
            command=name,
            error=f"Unknown command: '{name}'",
            error_code="UNKNOWN_COMMAND",
            suggestions=suggestions,
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "success"    : self.success,
            "command"    : self.command,
            "output"     : self.output,
            "data"       : self.data,
            "error"      : self.error,
            "error_code" : self.error_code,
            "suggestions": self.suggestions,
            "duration_ms": round(self.duration_ms, 1),
        }

    def to_cli_text(self) -> str:
        """Render as human-readable CLI output."""
        lines: list[str] = []
        if self.output:
            lines.append(self.output)
        if not self.success:
            lines.append(f"✗ {self.error}")
            for s in self.suggestions:
                lines.append(f"  → {s}")
        if self.duration_ms:
            lines.append(f"  ({self.duration_ms:.0f}ms)")
        return "\n".join(lines)


# ── Levenshtein-based closest-match ──────────────────────────────────────────

def _closest(name: str, candidates: list[str], max_dist: int = 3) -> list[str]:
    scored = [(c, _lev(name, c)) for c in candidates]
    return [c for c, d in sorted(scored, key=lambda x: x[1]) if d <= max_dist]


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if a[i-1] == b[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = temp
    return dp[n]
