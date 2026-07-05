"""
OpenRouter provider — routes to 100+ models via a single OpenAI-compatible API.

Set OPENROUTER_API_KEY to enable.
Optionally set OPENROUTER_DEFAULT_MODEL (defaults to openrouter/auto).

Docs: https://openrouter.ai/docs
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncGenerator, Any, Optional

import httpx

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
    ToolCall, UsageStats, Message,
)
from app.ai.providers.base import BaseProvider

log = logging.getLogger(__name__)

_BASE_URL     = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "openrouter/auto"
_ENV_KEY      = "OPENROUTER_API_KEY"

# OpenRouter billing is dynamic, so we track $0 here and let the usage endpoint
# report actuals. Overridden per-model if needed.
_PRICING: dict[str, tuple[float, float]] = {}


def _to_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result = []
    for m in messages:
        if isinstance(m.content, str):
            result.append({"role": m.role, "content": m.content})
        else:
            parts = []
            for part in m.content:
                if part.type == "text":
                    parts.append({"type": "text", "text": part.text})
                elif part.type == "image_url":
                    parts.append({"type": "image_url", "image_url": {"url": part.url}})
            result.append({"role": m.role, "content": parts})
    return result


def _to_tools(tools: list) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {
            "name":        t.name,
            "description": t.description,
            "parameters":  t.parameters,
        }}
        for t in tools
    ]


class OpenRouterProvider(BaseProvider):
    provider_id = "openrouter"

    def _env_key(self) -> str:
        return _ENV_KEY

    def default_model(self) -> str:
        import os
        return os.getenv("OPENROUTER_DEFAULT_MODEL", _DEFAULT_MODEL)

    def cost_per_token(self, model: str) -> tuple[float, float]:
        return _PRICING.get(model, (0.0, 0.0))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization":  f"Bearer {self._api_key()}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   "https://axon.ai",
            "X-Title":        "Axon AI Platform",
        }

    def _build_body(self, request: CompletionRequest, *, stream: bool = False) -> dict[str, Any]:
        model = self.resolve_model(request.model)

        # Extract system message
        system: Optional[str] = request.system
        messages = _to_messages(request.messages)

        if system:
            messages = [{"role": "system", "content": system}] + messages

        body: dict[str, Any] = {
            "model":       model,
            "messages":    messages,
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
            "stream":      stream,
        }
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.tools:
            body["tools"] = _to_tools(request.tools)
        return body

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        body = self._build_body(request, stream=False)
        async with httpx.AsyncClient(timeout=request.timeout) as client:
            resp = await client.post(
                f"{_BASE_URL}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choice   = data["choices"][0]
        message  = choice["message"]
        usage_d  = data.get("usage", {})
        model_id = data.get("model", self.resolve_model(request.model))

        content    = message.get("content") or ""
        tool_calls = []
        for tc in message.get("tool_calls") or []:
            fn  = tc.get("function", {})
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {"raw": args_raw}
            tool_calls.append(ToolCall(
                id=tc.get("id", str(uuid.uuid4())),
                name=fn.get("name", ""),
                arguments=args,
            ))

        in_t  = usage_d.get("prompt_tokens", 0)
        out_t = usage_d.get("completion_tokens", 0)
        usage = UsageStats(
            input_tokens=in_t, output_tokens=out_t,
            total_tokens=in_t + out_t,
            cost_usd=self.calculate_cost(model_id, in_t, out_t),
            provider=self.provider_id, model=model_id,
        )
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=usage,
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        body = self._build_body(request, stream=True)
        model_id = self.resolve_model(request.model)

        in_tokens = out_tokens = 0

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            async with client.stream(
                "POST",
                f"{_BASE_URL}/chat/completions",
                headers=self._headers(),
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for raw in resp.aiter_lines():
                    if not raw.startswith("data: "):
                        continue
                    payload = raw[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choice = chunk.get("choices", [{}])[0]
                    delta  = choice.get("delta", {})
                    text   = delta.get("content") or ""
                    if text:
                        yield StreamChunk(type="delta", text=text)
                        out_tokens += 1

                    usage_d = chunk.get("usage", {})
                    if usage_d:
                        in_tokens  = usage_d.get("prompt_tokens", in_tokens)
                        out_tokens = usage_d.get("completion_tokens", out_tokens)

        yield StreamChunk(
            type="usage",
            usage=UsageStats(
                input_tokens=in_tokens, output_tokens=out_tokens,
                total_tokens=in_tokens + out_tokens,
                cost_usd=self.calculate_cost(model_id, in_tokens, out_tokens),
                provider=self.provider_id, model=model_id,
            ),
        )
        yield StreamChunk(type="done")
