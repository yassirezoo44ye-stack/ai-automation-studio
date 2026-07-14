"""
OpenAI (GPT) provider implementation.
All OpenAI-specific API calls are isolated to this file.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Any

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
    ToolCall, UsageStats, Message,
)
from app.ai.providers.base import BaseProvider

_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":         (2.5  / 1e6, 10.0 / 1e6),
    "gpt-4o-mini":    (0.15 / 1e6, 0.6  / 1e6),
    "gpt-4-turbo":    (10.0 / 1e6, 30.0 / 1e6),
    "o3":             (10.0 / 1e6, 40.0 / 1e6),
    "o4-mini":        (1.1  / 1e6, 4.4  / 1e6),
}
_DEFAULT_MODEL = "gpt-4o-mini"


def _to_sdk_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result = []
    for m in messages:
        role = m.role if m.role != "tool" else "tool"
        if isinstance(m.content, str):
            result.append({"role": role, "content": m.content})
        else:
            parts: list[dict] = []
            for part in m.content:
                if part.type == "text":
                    parts.append({"type": "text", "text": part.text})
                elif part.type == "image_url":
                    parts.append({"type": "image_url", "image_url": {"url": part.url}})
                elif part.type == "tool_result":
                    content = part.content if isinstance(part.content, str) else part.content[0].text
                    result.append({
                        "role":         "tool",
                        "tool_call_id": part.tool_use_id,
                        "content":      content,
                    })
                    continue
            if parts:
                result.append({"role": role, "content": parts})
    return result


def _to_sdk_tools(tools: list) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name":        t.name,
                "description": t.description,
                "parameters":  t.parameters,
            },
        }
        for t in tools
    ]


class OpenAIProvider(BaseProvider):
    provider_id = "openai"

    def _env_key(self) -> str:
        return "OPENAI_API_KEY"

    def _get_client(self):  # type: ignore[return]
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
            return AsyncOpenAI(api_key=self._api_key())
        except ImportError as e:
            raise RuntimeError("openai package not installed. Run: pip install openai") from e

    def default_model(self) -> str:
        return _DEFAULT_MODEL

    def cost_per_token(self, model: str) -> tuple[float, float]:
        for prefix, pricing in _PRICING.items():
            if model.startswith(prefix):
                return pricing
        return _PRICING[_DEFAULT_MODEL]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        model = self.resolve_model(request.model)
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model":    model,
            "messages": _to_sdk_messages(request.messages),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.system:
            kwargs["messages"].insert(0, {"role": "system", "content": request.system})
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        if request.tools:
            kwargs["tools"] = _to_sdk_tools(request.tools)

        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        content_text = msg.content or ""
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                ))

        usage = resp.usage
        stats = UsageStats(
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            cost_usd=self.calculate_cost(
                model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            ),
            provider=self.provider_id,
            model=model,
        )
        return CompletionResponse(
            id=resp.id,
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=stats,
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        model = self.resolve_model(request.model)
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model":       model,
            "messages":    _to_sdk_messages(request.messages),
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
            "stream":      True,
            "stream_options": {"include_usage": True},
        }
        if request.system:
            kwargs["messages"].insert(0, {"role": "system", "content": request.system})
        if request.tools:
            kwargs["tools"] = _to_sdk_tools(request.tools)

        input_tokens = output_tokens = 0

        async for chunk in await client.chat.completions.create(**kwargs):
            if chunk.usage:
                input_tokens  = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamChunk(type="delta", text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.function and tc.function.name:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamChunk(
                            type="tool_call",
                            tool_call=ToolCall(
                                id=tc.id or "", name=tc.function.name, arguments=args
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
