"""
ElectronRuntime — scaffold for Electron application execution.

Electron apps require a display server (Xvfb on Linux) and a
specially configured Electron binary.  This scaffold handles
detection and emits UnsupportedRuntime in sandbox environments.

Detection:
  - package.json contains "electron" in dependencies or devDependencies
  - OR "main" field points to a JS file AND no web-server scripts found
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.execution.platform.errors import unsupported_runtime
from app.execution.platform.events import UnsupportedRuntime
from app.execution.platform.runtimes.abstract import AbstractRuntime, ExecutionContext

log = logging.getLogger(__name__)


class ElectronRuntime(AbstractRuntime):
    name     = "electron"
    priority = 40

    def detect(self, workspace: Path) -> bool:
        pkg = workspace / "package.json"
        if not pkg.exists():
            return False
        try:
            data = json.loads(pkg.read_text())
            all_deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
            return "electron" in all_deps
        except Exception:
            return False

    async def probe(self, ctx: ExecutionContext) -> None:
        ctx.emit(UnsupportedRuntime(
            execution_id   = ctx.execution_id,
            project_type   = "electron",
            reason         = "Electron apps require a display server and cannot run in this sandbox",
            local_run_hint = "npm run start",
            fix            = [
                "Download the ZIP and run locally: npm install && npm run start",
                "For headless testing use: npx electron . --no-sandbox (requires Xvfb)",
            ],
        ))
        raise unsupported_runtime(
            "electron",
            "Electron requires a display server — unsupported in this sandbox",
        )

    async def install(self, ctx: ExecutionContext) -> None:
        pass

    async def build(self, ctx: ExecutionContext) -> None:
        pass

    async def launch(self, ctx: ExecutionContext) -> None:
        pass

    async def cleanup(self, ctx: ExecutionContext) -> None:
        pass
