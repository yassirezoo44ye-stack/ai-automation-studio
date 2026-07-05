"""
Structured error system — Phase 5.

Every runtime failure is expressed as a StructuredError dict:

  {
    type:        "error",
    category:    str,         # "missing_runtime" | "execution" | "preflight" | "config"
    message:     str,         # human-readable, no stack traces, no internal paths
    fix:         list[str],   # ordered list of actionable steps
    severity:    str,         # "low" | "medium" | "high"
    recoverable: bool,
    ...extra                  # e.g. missing_tool, project_type
  }

No FileNotFoundError text, no raw subprocess output ever reaches the client.
"""
from __future__ import annotations

import json
from typing import Literal

Severity = Literal["low", "medium", "high"]


def sse_error(
    category: str,
    message: str,
    fix: list[str],
    severity: Severity = "high",
    recoverable: bool = False,
    **extra,
) -> str:
    """Return a formatted SSE data line containing a StructuredError payload."""
    payload = {
        "type":        "error",
        "category":    category,
        "message":     message,
        "fix":         fix,
        "severity":    severity,
        "recoverable": recoverable,
        **extra,
    }
    return f"data: {json.dumps(payload)}\n\n"


class StructuredRuntimeError(Exception):
    """
    Raised by RuntimeControlPlane.require() when a tool is unavailable.
    Never exposes OS-level FileNotFoundError details.
    """

    def __init__(self, tool: str, fix: list[str] | None = None) -> None:
        self.tool = tool
        self.fix: list[str] = fix or [
            f"Install {tool} and ensure it is on PATH.",
            "Then restart the server so the runtime registry refreshes.",
        ]
        super().__init__(f"Runtime tool not available: {tool!r}")

    def to_sse(self) -> str:
        return sse_error(
            category="missing_runtime",
            message=f"Required runtime not available: {self.tool}",
            fix=self.fix,
            severity="high",
            recoverable=False,
            missing_tool=self.tool,
        )
