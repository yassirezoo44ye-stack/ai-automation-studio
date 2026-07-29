"""
ImageAgent tests (app/agents/builtin/image_agent.py) — Manus M5: image
generation AI tool. Mirrors test_search_agent.py's httpx-mocking
convention and test_agent_deliverables.py's WORKSPACES-patching pattern
(the generated image is registered as a downloadable deliverable).

No live network calls, no real files written outside tmp_path.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ctx(args: str, *, organization_id=None):
    from app.agents.base import AgentContext
    return AgentContext(
        input=args, args=args, kernel=None, memory=None, run_id="r1",
        organization_id=organization_id,
    )


class TestImageAgentConfiguration:
    def test_no_prompt_fails_without_network_call(self):
        from app.agents.builtin.image_agent import ImageAgent
        with patch("httpx.AsyncClient.post") as fake_post:
            result = run(ImageAgent().execute(_ctx("")))
        assert result.success is False
        assert "prompt" in result.output.lower()
        fake_post.assert_not_called()

    def test_missing_api_key_fails_gracefully_without_network_call(self):
        from app.agents.builtin.image_agent import ImageAgent
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch("httpx.AsyncClient.post") as fake_post:
                result = run(ImageAgent().execute(_ctx("a red panda")))
        assert result.success is False
        assert "OPENAI_API_KEY" in result.output
        fake_post.assert_not_called()

    def test_permissions_declare_network_and_filesystem_write(self):
        from app.agents.builtin.image_agent import ImageAgent
        perms = ImageAgent().permissions
        assert perms.can_access_network is True
        assert perms.can_write_filesystem is True


class TestImageAgentExecution:
    def test_successful_generation_registers_a_deliverable(self, tmp_path):
        from app.agents.builtin.image_agent import ImageAgent
        import app.agents.deliverables as deliverables
        import app.agents.builtin.image_agent as image_agent_mod

        fake_gen_response = MagicMock()
        fake_gen_response.raise_for_status = MagicMock()
        fake_gen_response.json = MagicMock(return_value={
            "data": [{"url": "https://images.example/generated.png"}],
        })
        fake_download_response = MagicMock()
        fake_download_response.raise_for_status = MagicMock()
        fake_download_response.content = b"\x89PNG\r\n\x1a\nfakepixels"

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             patch.object(image_agent_mod, "WORKSPACES", tmp_path), \
             patch.object(deliverables, "WORKSPACES", tmp_path), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_gen_response)), \
             patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_download_response)), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(ImageAgent().execute(_ctx("a red panda", organization_id="org-a")))

        assert result.success is True
        assert "deliverable_id" in result.data
        entry = deliverables.get(result.data["deliverable_id"])
        assert entry is not None
        assert entry["organization_id"] == "org-a"
        assert entry["path"].endswith(".png")

    def test_http_error_on_generation_fails_without_raising(self):
        from app.agents.builtin.image_agent import ImageAgent

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.post",
                   new=AsyncMock(side_effect=__import__("httpx").ConnectError("boom"))), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(ImageAgent().execute(_ctx("a red panda")))  # must not raise

        assert result.success is False
        assert "Image generation failed" in result.output

    def test_unexpected_response_shape_fails_cleanly(self):
        from app.agents.builtin.image_agent import ImageAgent

        fake_gen_response = MagicMock()
        fake_gen_response.raise_for_status = MagicMock()
        fake_gen_response.json = MagicMock(return_value={"data": []})  # missing [0]

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_gen_response)), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(ImageAgent().execute(_ctx("a red panda")))

        assert result.success is False
        assert "unexpected response" in result.output.lower()


class TestImageIntentRouting:
    def test_image_alias_resolves_to_image_intent_with_args(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("image a sunset over mountains")
        assert ir.intent == "image"
        assert ir.args == "a sunset over mountains"

    def test_draw_alias_resolves_to_image(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("draw a cat wearing a hat")
        assert ir.intent == "image"


class TestImageAgentLoaderRegistration:
    def test_module_exposes_a_module_level_agent_instance(self):
        import app.agents.builtin.image_agent as mod
        from app.agents.base import EvolvableAgent
        assert isinstance(mod.agent, EvolvableAgent)
        assert mod.agent.name == "image"
