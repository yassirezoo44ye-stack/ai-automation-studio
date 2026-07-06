"""
Driver: Node.js projects.

Thin wrapper around PhaseRunner.  The driver's only job is:
  1. Check if this driver can handle the project
  2. Instantiate PhaseRunner
  3. Translate (event_type, payload) tuples into SSE strings

All runtime logic lives in app.execution.js_runtime.phases.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.execution.js_runtime.phases import PhaseRunner
from app.runtime import registry

_SERVER_PROJECT_TYPES = {"express", "koa", "nestjs", "node"}
_BUILD_PROJECT_TYPES  = {"react", "vue", "svelte", "vite", "nextjs", "nuxt"}
_ALL_NODE_TYPES       = _SERVER_PROJECT_TYPES | _BUILD_PROJECT_TYPES | {"node_app"}


def can_handle(info) -> bool:
    if info.run_strategy not in ("node", "npm") and info.project_type not in _ALL_NODE_TYPES:
        return False
    return registry.has("node") or registry.has("npm")


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    runner = PhaseRunner(project_id=project_id, ws=ws, info=info)
    async for event_type, payload in runner.run():
        yield f"data: {json.dumps({'type': event_type, **payload})}\n\n"
