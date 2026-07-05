"""
Google Gemini provider implementation.
All Gemini-specific API calls are isolated to this file.
"""
from __future__ import annotations

from typing import AsyncGenerator, Any

from app.ai.models import (
    CompletionRequest, CompletionResponse, StreamChunk,
    ToolCall, UsageStats, Message,
)
from app.ai.providers.base import BaseProvider

_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro":      (1.25 / 1e6, 10.0 / 1e6),
    "gemini-2.5-flash":    (0.075/ 1e6, 0.3  / 1e6),
    "gemini-2.0-flash":    (0.1  / 1e6, 0.4  / 1e6),
    "gemini-1.5-pro":      (1.25 / 1e6, 5.0  / 1e6),
    "gemini-1.5-flash":    (0.075/ 1e6, 0.3  / 1e6),
}
_DEFAULT_MODEL = "gemini-2.5-flash"


def _to_gemini_contents(messages: list[Message]) -> list[dict[str, Any]]:
    contents = []
    for m in messages:
        if m.role == "system":
            continue
        role = "model" if m.role == "assistant" else "user"
        text = m.content if isinstance(m.content, str) else " ".join(
            p.text for p in m.content if p.type == "text"
        )
        contents.append({"role": role, "parts": [{"text": text}]})
    return contents


def _to_gemini_tools(tools: list) -> list[dict[str, Any]]:
    return [{
        "function_declarations": [
            {
                "name":        t.name,
                "description": t.description,
                "parameters":  t.parameters,
            }
            for t in tools
        ]
    }]


class GeminiProvider(BaseProvider):
    provider_id = "gemini"

    def _env_key(self) -> str:
        return "GEMINI_API_KEY"

    def _get_client(self):  # type: ignore[return]
        try:
            import google.generativeai as genai  # type: ignore[import]
            genai.configure(api_key=self._api_key())
            return genai
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            ) from e

    def default_model(self) -> str:
        return _DEFAULT_MODEL

    def cost_per_token(self, model: str) -> tuple[float, float]:
        for prefix, pricing in _PRICING.items():
            if model.startswith(prefix):
                return pricing
        return _PRICING[_DEFAULT_MODEL]

    def _build_config(self, request: CompletionRequest) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "temperature":       request.temperature,
        }
        if request.top_p is not None:
            cfg["top_p"] = request.top_p
        return cfg

    def _extract_system(self, messages: list[Message], override: str | None) -> str | None:
        if override:
            return override
        for m in messages:
            if m.role == "system":
                return m.content if isinstance(m.content, str) else None
        return None

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        import google.generativeai as genai  # type: ignore[import]
        from google.generativeai.types import GenerationConfig  # type: ignore[import]

        genai.configure(api_key=self._api_key())
        model_name = self.resolve_model(request.model)

        system = self._extract_system(request.messages, request.system)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
            generation_config=GenerationConfig(**self._build_config(request)),
            tools=_to_gemini_tools(request.tools) if request.tools else None,
        )

        contents = _to_gemini_contents(request.messages)
        resp = await model.generate_content_async(contents)

        content_text = resp.text or ""
        tool_calls: list[ToolCall] = []
        for part in (resp.parts or []):
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=fc.name,
                    name=fc.name,
                    arguments=dict(fc.args or {}),
                ))

        meta = resp.usage_metadata
        input_tokens  = meta.prompt_token_count     if meta else 0
        output_tokens = meta.candidates_token_count if meta else 0
        cost = self.calculate_cost(model_name, input_tokens, output_tokens)

        return CompletionResponse(
            id=f"gemini-{id(resp)}",
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=str(resp.candidates[0].finish_reason) if resp.candidates else "stop",
            usage=UsageStats(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost,
                provider=self.provider_id,
                model=model_name,
            ),
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        import google.generativeai as genai  # type: ignore[import]
        from google.generativeai.types import GenerationConfig  # type: ignore[import]

        genai.configure(api_key=self._api_key())
        model_name = self.resolve_model(request.model)
        system = self._extract_system(request.messages, request.system)

        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
            generation_config=GenerationConfig(**self._build_config(request)),
            tools=_to_gemini_tools(request.tools) if request.tools else None,
        )

        contents = _to_gemini_contents(request.messages)
        input_tokens = output_tokens = 0

        async for chunk in await model.generate_content_async(contents, stream=True):
            if chunk.text:
                yield StreamChunk(type="delta", text=chunk.text)
            if chunk.usage_metadata:
                meta = chunk.usage_metadata
                input_tokens  = meta.prompt_token_count     or input_tokens
                output_tokens = meta.candidates_token_count or output_tokens

        cost = self.calculate_cost(model_name, input_tokens, output_tokens)
        yield StreamChunk(
            type="usage",
            usage=UsageStats(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost,
                provider=self.provider_id,
                model=model_name,
            ),
        )
        yield StreamChunk(type="done")
