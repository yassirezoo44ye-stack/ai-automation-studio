"""AIProvider backed by the Anthropic Messages API.

Structured generation uses tool-use (forcing the model to call one
fixed-schema tool) rather than asking for "JSON" in free text and hoping —
Anthropic validates the tool call against `input_schema` on its side, so a
non-conforming response never reaches this process as something we'd have
to sniff out of markdown fences or truncated JSON.
"""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.services.ai.provider import AIGenerationError, AIProvider

log = logging.getLogger(__name__)

_STRUCTURED_TOOL_NAME = "emit_result"


class AnthropicProvider(AIProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            log.warning("anthropic generate() failed: %s", exc)
            raise AIGenerationError(f"AI provider request failed: {exc}") from exc

        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise AIGenerationError("AI provider returned no text content")
        return "\n".join(text_blocks)

    async def generate_structured(
        self, *, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 2048,
    ) -> dict[str, Any] | list[Any]:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": _STRUCTURED_TOOL_NAME,
                    "description": "Return the result matching the required schema. Always call this.",
                    "input_schema": schema,
                }],
                tool_choice={"type": "tool", "name": _STRUCTURED_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            log.warning("anthropic generate_structured() failed: %s", exc)
            raise AIGenerationError(f"AI provider request failed: {exc}") from exc

        for block in response.content:
            if block.type == "tool_use" and block.name == _STRUCTURED_TOOL_NAME:
                return block.input
        raise AIGenerationError("AI provider did not return structured output")
