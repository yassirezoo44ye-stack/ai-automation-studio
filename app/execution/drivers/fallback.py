"""
Fallback driver — catches everything the other drivers can't handle.
Shows a helpful unsupported message with runtime context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.runtime import registry
from app.runtime.errors import sse_error


def can_handle(info) -> bool:
    return True  # always matches — must be last in the chain


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    pt = info.project_type
    reason = info.unsupported_reason or f"{pt} is not supported in this sandbox."
    hint = info.local_run_hint or "Run this project in a local terminal."

    available = [n for n, r in registry.to_dict().items() if r.get("available")]

    yield sse_error(
        category="unsupported",
        message=reason,
        fix=[hint, "Check the project type is supported (Python, Node.js, HTML)"],
        severity="medium",
        recoverable=False,
        project_type=pt,
        local_run_hint=hint,
        available_runtimes=available,
    )
