"""Image agent — text-to-image generation via OpenAI's Images API (DALL-E).

Reuses OPENAI_API_KEY — the same credential the OpenAI chat provider
already uses (app/ai/providers/openai.py), so there's no separate key to
configure. Absent key returns a clear, actionable failure result, never a
crash. The generated image is saved under WORKSPACES and registered as a
deliverable (app/agents/deliverables.py — same mechanism DeployAgent's zip
archives use), so it's downloadable through the existing AgentOS Terminal
"Download" button with no new frontend surface.
"""
from __future__ import annotations

import logging
import os
import uuid

import httpx

from app.agents import deliverables
from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent
from app.core.config import WORKSPACES

log = logging.getLogger(__name__)

_IMAGES_URL    = "https://api.openai.com/v1/images/generations"
_ENV_KEY       = "OPENAI_API_KEY"
_DEFAULT_MODEL = "dall-e-3"
_DEFAULT_SIZE  = "1024x1024"


class ImageAgent(EvolvableAgent):
    name        = "image"
    description = "Generate an image from a text prompt (OpenAI DALL-E)"
    group       = "creative"

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions(can_access_network=True, can_write_filesystem=True)

    async def execute(self, ctx: AgentContext) -> AgentResult:
        prompt = ctx.args.strip() or ctx.input.strip()
        if not prompt:
            return AgentResult.fail(self.name, "No image prompt. Usage: image <description>")

        api_key = os.getenv(_ENV_KEY, "")
        if not api_key:
            return AgentResult.fail(
                self.name,
                f"Image generation isn't configured — set {_ENV_KEY} to enable it.",
                data={"prompt": prompt},
            )

        await ctx.step(f"Generating image: {prompt!r}", "info")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    _IMAGES_URL,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": _DEFAULT_MODEL, "prompt": prompt, "n": 1, "size": _DEFAULT_SIZE},
                )
                resp.raise_for_status()
                data = resp.json()
                image_url = data["data"][0]["url"]

                await ctx.step("Downloading generated image", "file")
                img_resp = await client.get(image_url)
                img_resp.raise_for_status()
                image_bytes = img_resp.content
        except httpx.HTTPStatusError as exc:
            return AgentResult.fail(
                self.name, f"Image generation failed: HTTP {exc.response.status_code}",
                data={"prompt": prompt},
            )
        except httpx.HTTPError as exc:
            return AgentResult.fail(self.name, f"Image generation failed: {exc}", data={"prompt": prompt})
        except (KeyError, IndexError):
            return AgentResult.fail(
                self.name, "Image generation returned an unexpected response",
                data={"prompt": prompt},
            )

        out_dir = WORKSPACES / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        image_path = out_dir / f"image_{uuid.uuid4().hex[:8]}.png"
        image_path.write_bytes(image_bytes)

        deliverable_id = deliverables.register(
            image_path, run_id=ctx.run_id, agent=self.name, label=image_path.name,
            organization_id=ctx.organization_id,
        )
        result_data: dict = {"prompt": prompt}
        if deliverable_id:
            result_data["deliverable_id"]    = deliverable_id
            result_data["deliverable_label"] = image_path.name
            await ctx.step(f"Deliverable ready for download: {image_path.name}", "success")

        return AgentResult.ok(
            self.name, f"Generated image for {prompt!r}: {image_path.name}",
            data=result_data,
        )

    def performance_hint(self) -> dict:
        return {"complexity": "medium", "io_bound": True, "timeout_s": 60}


agent = ImageAgent()
