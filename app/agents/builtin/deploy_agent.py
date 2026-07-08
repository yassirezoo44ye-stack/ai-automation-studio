"""Deploy agent — packages and deploys a project."""
from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)


class DeployAgent(EvolvableAgent):
    name        = "deploy"
    description = "Package and deploy a project (Render, Docker, or zip)"
    group       = "deployment"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        parts     = shlex.split(ctx.args) if ctx.args else []
        workspace = parts[0] if parts else ctx.workspace
        target    = parts[1] if len(parts) > 1 else "auto"

        if not workspace:
            return AgentResult.fail(
                self.name,
                "No workspace specified. Usage: deploy <path> [target]",
                data={"targets": ["render", "docker", "zip", "auto"]},
            )

        ws = Path(workspace).expanduser().resolve()
        if not ws.exists():
            return AgentResult.fail(self.name, f"Workspace not found: {workspace}")

        # Detect deploy target
        if target == "auto":
            target = _detect_target(ws)

        steps: list[str] = []

        try:
            if target == "zip":
                result = await self._zip_deploy(ws, steps)
            elif target == "render":
                result = await self._render_deploy(ws, steps)
            elif target == "docker":
                result = await self._docker_deploy(ws, steps)
            else:
                return AgentResult.fail(
                    self.name, f"Unknown deploy target: {target}",
                    data={"supported": ["render", "docker", "zip"]},
                )
            return result
        except Exception as exc:
            return AgentResult.fail(self.name, str(exc),
                                    data={"steps": steps, "workspace": str(ws)})

    async def _zip_deploy(self, ws: Path, steps: list) -> AgentResult:
        import shutil, uuid
        out_dir = Path(os.getenv("WORKSPACES", "/tmp")) / "deploys"
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"{ws.name}_{uuid.uuid4().hex[:8]}.zip"

        steps.append(f"Creating zip archive: {zip_path.name}")
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", ws)
        steps.append(f"Archive size: {zip_path.stat().st_size / 1024:.1f} KB")

        return AgentResult.ok(
            self.name,
            f"Deployed as zip: {zip_path.name}",
            data={"zip": str(zip_path), "steps": steps},
        )

    async def _render_deploy(self, ws: Path, steps: list) -> AgentResult:
        render_yaml = ws / "render.yaml"
        if not render_yaml.exists():
            return AgentResult.fail(
                self.name,
                "render.yaml not found — create it first",
                data={"steps": steps},
            )
        steps.append("render.yaml detected")
        steps.append("Note: Render deployment requires Render CLI — push to GitHub to trigger auto-deploy")
        return AgentResult.ok(
            self.name,
            "Render deployment configured. Push to GitHub to trigger deploy.",
            data={"steps": steps, "render_yaml": str(render_yaml)},
        )

    async def _docker_deploy(self, ws: Path, steps: list) -> AgentResult:
        dockerfile = ws / "Dockerfile"
        if not dockerfile.exists():
            return AgentResult.fail(
                self.name, "Dockerfile not found",
                data={"steps": steps},
            )
        steps.append("Dockerfile detected")
        steps.append("Docker build would require: docker build -t <name> .")
        return AgentResult.ok(
            self.name,
            "Docker deployment ready. Run: docker build -t <name> . && docker run <name>",
            data={"steps": steps, "dockerfile": str(dockerfile)},
        )

    def performance_hint(self) -> dict:
        return {"complexity": "medium", "io_bound": True}


def _detect_target(ws: Path) -> str:
    if (ws / "render.yaml").exists():
        return "render"
    if (ws / "Dockerfile").exists():
        return "docker"
    return "zip"


agent = DeployAgent()
