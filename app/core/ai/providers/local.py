"""
Local model provider — supports Ollama, llama.cpp, LM Studio, and any
OpenAI-compatible server.

Set LOCAL_MODEL_BASE_URL to point at a local server.
Default: http://localhost:11434/v1  (Ollama's default)

This provider is available when LOCAL_MODEL_BASE_URL is set, regardless of an API key.
"""
from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator, Any

import httpx

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
    UsageStats,
)
from app.ai.providers.base import BaseProvider

log = logging.getLogger(__name__)

_ENV_URL   = "LOCAL_MODEL_BASE_URL"
_ENV_MODEL = "LOCAL_MODEL_DEFAULT"
_DEFAULT_BASE = "http://localhost:11434/v1"
_DEFAULT_MODEL = "llama3"


class LocalProvider(BaseProvider):
    """
    Adapter for any local OpenAI-compatible server (Ollama, LM Studio, llama.cpp).

    Falls back gracefully if the server is unreachable — `is_available` returns
    False so the registry skips it during failover.
    """
    provider_id = "local"

    def _env_key(self) -> str:
        return _ENV_URL  # availability based on URL, not API key

    @property
    def is_available(self) -> bool:
        return bool(os.getenv(_ENV_URL, ""))

    def _base_url(self) -> str:
        return os.getenv(_ENV_URL, _DEFAULT_BASE).rstrip("/")

    def _api_key(self) -> str:
        return os.getenv("LOCAL_MODEL_API_KEY", "local")

    def default_model(self) -> str:
        return os.getenv(_ENV_MODEL, _DEFAULT_MODEL)

    def cost_per_token(self, model: str) -> tuple[float, float]:
        return (0.0, 0.0)  # local = free

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type":  "application/json",
        }

    def _build_body(
        self,
        request: CompletionRequest,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        model = self.resolve_model(request.model)

        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for m in request.messages:
            if m.role == "system":
                continue
            content = m.content if isinstance(m.content, str) else str(m.content)
            messages.append({"role": m.role, "content": content})

        return {
            "model":       model,
            "messages":    messages,
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
            "stream":      stream,
        }

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        body     = self._build_body(request, stream=False)
        model_id = self.resolve_model(request.model)

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            resp = await client.post(
                f"{self._base_url()}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choice  = data["choices"][0]
        content = choice["message"].get("content") or ""
        usage_d = data.get("usage", {})
        in_t    = usage_d.get("prompt_tokens", 0)
        out_t   = usage_d.get("completion_tokens", 0)

        return CompletionResponse(
            content=content,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=UsageStats(
                input_tokens=in_t, output_tokens=out_t, total_tokens=in_t + out_t,
                provider=self.provider_id, model=model_id,
            ),
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        body     = self._build_body(request, stream=True)
        model_id = self.resolve_model(request.model)
        out_tokens = 0

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url()}/chat/completions",
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
                    text = (chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content") or "")
                    if text:
                        yield StreamChunk(type="delta", text=text)
                        out_tokens += 1

        yield StreamChunk(
            type="usage",
            usage=UsageStats(
                input_tokens=0, output_tokens=out_tokens, total_tokens=out_tokens,
                provider=self.provider_id, model=model_id,
            ),
        )
        yield StreamChunk(type="done")
