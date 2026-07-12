"""Build agent — runs the build phase for a project."""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)

_BUILD_COMMANDS: dict[str, list[str]] = {
    "package.json"    : ["npm", "run", "build"],
    "pyproject.toml"  : ["python", "-m", "build"],
    "Makefile"        : ["make", "build"],
    "requirements.txt": ["echo", "Python project — no build step required"],
}


class BuildAgent(EvolvableAgent):
    name        = "build"
    description = "Build a project (auto-detects build tool)"
    group       = "execution"

    @property
    def permissions(self) -> AgentPermissions:
        # execute() itself already enforces a 300s subprocess.run timeout
        # (see below) — run()'s own asyncio.wait_for wrapper must not cut
        # this off earlier at the generic 30s default, or every build
        # would spuriously report "timed out" the instant the (already
        # complete) subprocess call returns control to the event loop.
        return AgentPermissions(can_execute_subprocess=True, max_execution_seconds=310.0)

    async def execute(self, ctx: AgentContext) -> AgentResult:
        parts    = shlex.split(ctx.args) if ctx.args else []
        workspace = parts[0] if parts else ctx.workspace
        if not workspace:
            return AgentResult.fail(self.name,
                                    "No workspace specified. Usage: build <path>")

        ws = Path(workspace).expanduser().resolve()
        if not ws.exists():
            return AgentResult.fail(self.name, f"Workspace not found: {workspace}")

        cmd = _detect_build_cmd(ws)
        if cmd is None:
            return AgentResult.fail(
                self.name,
                f"No build system detected in {ws.name}. "
                f"Supported: {', '.join(_BUILD_COMMANDS.keys())}",
            )

        try:
            proc = subprocess.run(
                cmd, cwd=ws, capture_output=True, text=True, timeout=300,
            )
            success = proc.returncode == 0
            output  = (proc.stdout or "") + (proc.stderr or "")
            return AgentResult(
                agent   = self.name,
                success = success,
                output  = output[-2000:] if output else "Build complete",
                data    = {
                    "workspace"  : str(ws),
                    "command"    : cmd,
                    "exit_code"  : proc.returncode,
                    "stdout_tail": proc.stdout[-1000:] if proc.stdout else "",
                    "stderr_tail": proc.stderr[-500:]  if proc.stderr else "",
                },
                error = f"Build exited {proc.returncode}" if not success else None,
            )
        except subprocess.TimeoutExpired:
            return AgentResult.fail(self.name, "Build timed out after 300s",
                                    data={"workspace": str(ws), "command": cmd})
        except Exception as exc:
            return AgentResult.fail(self.name, str(exc))

    def performance_hint(self) -> dict:
        return {"complexity": "medium", "io_bound": True, "timeout_s": 300}


def _detect_build_cmd(ws: Path) -> list[str] | None:
    for filename, cmd in _BUILD_COMMANDS.items():
        if (ws / filename).exists():
            return cmd
    return None


agent = BuildAgent()
