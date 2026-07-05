"""
Anthropic (Claude) provider implementation.
All Anthropic-specific API calls are isolated to this file.
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator, Any

import anthropic as sdk

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
    ToolCall, UsageStats, Message,
)
from app.ai.providers.base import BaseProvider

# ── Pricing (USD per token) — update when pricing changes ────────────────────
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":             (15.0 / 1e6,  75.0 / 1e6),
    "claude-sonnet-5":             (3.0  / 1e6,  15.0 / 1e6),
    "claude-sonnet-4-6":           (3.0  / 1e6,  15.0 / 1e6),
    "claude-haiku-4-5-20251001":   (0.25 / 1e6,  1.25 / 1e6),
}
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _to_sdk_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert gateway messages to Anthropic SDK format."""
    result = []
    for m in messages:
        if m.role == "system":
            continue  # system handled separately
        if isinstance(m.content, str):
            result.append({"role": m.role, "content": m.content})
        else:
            parts = []
            for part in m.content:
                if part.type == "text":
                    parts.append({"type": "text", "text": part.text})
                elif part.type == "image_url":
                    parts.append({
                        "type":   "image",
                        "source": {"type": "url", "url": part.url},
                    })
                elif part.type == "tool_use":
                    parts.append({
                        "type":  "tool_use",
                        "id":    part.id,
                        "name":  part.name,
                        "input": part.input,
                    })
                elif part.type == "tool_result":
                    content = part.content if isinstance(part.content, str) else part.content[0].text
                    parts.append({
                        "type":        "tool_result",
                        "tool_use_id": part.tool_use_id,
                        "content":     content,
                        "is_error":    part.is_error,
                    })
            result.append({"role": m.role, "content": parts})
    return result


def _extract_system(messages: list[Message], override: str | None) -> str | None:
    if override:
        return override
    for m in messages:
        if m.role == "system":
            return m.content if isinstance(m.content, str) else None
    return None


def _to_sdk_tools(tools: list) -> list[dict[str, Any]]:
    return [
        {
            "name":         t.name,
            "description":  t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _build_kwargs(request: CompletionRequest, model: str) -> dict[str, Any]:
    system = _extract_system(request.messages, request.system)
    kwargs: dict[str, Any] = {
        "model":      model,
        "max_tokens": request.max_tokens,
        "messages":   _to_sdk_messages(request.messages),
    }
    if system:
        kwargs["system"] = system
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.tools:
        kwargs["tools"] = _to_sdk_tools(request.tools)
    return kwargs


class AnthropicProvider(BaseProvider):
    provider_id = "anthropic"

    def _client(self) -> sdk.AsyncAnthropic:
        return sdk.AsyncAnthropic(api_key=self._api_key())

    def default_model(self) -> str:
        return _DEFAULT_MODEL

    def cost_per_token(self, model: str) -> tuple[float, float]:
        for prefix, pricing in _PRICING.items():
            if model.startswith(prefix):
                return pricing
        return _PRICING[_DEFAULT_MODEL]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = self.resolve_model(request.model)
        client = self._client()
        kwargs = _build_kwargs(request, model)

        msg = await client.messages.create(**kwargs)

        content_text = ""
        tool_calls: list[ToolCall] = []

        for block in msg.content:
            if hasattr(block, "text"):
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=block.input
                ))

        usage = UsageStats(
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            total_tokens=msg.usage.input_tokens + msg.usage.output_tokens,
            cost_usd=self.calculate_cost(model, msg.usage.input_tokens, msg.usage.output_tokens),
            provider=self.provider_id,
            model=model,
        )
        return CompletionResponse(
            id=msg.id,
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=msg.stop_reason or "stop",
            usage=usage,
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        model = self.resolve_model(request.model)
        client = self._client()
        kwargs = _build_kwargs(request, model)

        input_tokens = 0
        output_tokens = 0

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield StreamChunk(type="delta", text=text)
                output_tokens += 1  # approximate; exact count below

            final = await stream.get_final_message()
            input_tokens  = final.usage.input_tokens
            output_tokens = final.usage.output_tokens

            # Emit any tool calls from final message
            for block in final.content:
                if block.type == "tool_use":
                    yield StreamChunk(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=block.id, name=block.name, arguments=block.input
                        ),
                    )

        cost = self.calculate_cost(model, input_tokens, output_tokens)
        yield StreamChunk(
            type="usage",
            usage=UsageStats(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost,
                provider=self.provider_id,
                model=model,
            ),
        )
        yield StreamChunk(type="done")
