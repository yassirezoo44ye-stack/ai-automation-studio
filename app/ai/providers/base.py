"""
Abstract base class for all AI providers.
Every provider must implement these methods — no provider-specific logic
may appear anywhere else in the codebase.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import AsyncGenerator

from app.ai.models import CompletionRequest, CompletionResponse, StreamChunk


class BaseProvider(ABC):
    """All provider implementations inherit from this class."""

    #: Must match a ProviderID enum value
    provider_id: str

    # ── Required overrides ────────────────────────────────────────────────────

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Non-streaming completion. Returns the full response."""
        ...

    @abstractmethod
    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """Streaming completion. Yields StreamChunk objects."""
        ...

    @abstractmethod
    def default_model(self) -> str:
        """Return the default model ID for this provider."""
        ...

    @abstractmethod
    def cost_per_token(self, model: str) -> tuple[float, float]:
        """Return (cost_per_input_token_usd, cost_per_output_token_usd)."""
        ...

    # ── Availability ──────────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """Returns True if the required API key is set."""
        return bool(self._api_key())

    def _api_key(self) -> str:
        """Return the configured API key or empty string."""
        return os.getenv(self._env_key(), "")

    def _env_key(self) -> str:
        """Environment variable name for this provider's API key."""
        return f"{self.provider_id.upper()}_API_KEY"

    # ── Cost calculation ──────────────────────────────────────────────────────

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        in_cost, out_cost = self.cost_per_token(model)
        return round(input_tokens * in_cost + output_tokens * out_cost, 8)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def resolve_model(self, model: str | None) -> str:
        return model or self.default_model()

    def __repr__(self) -> str:
        return f"<Provider:{self.provider_id} available={self.is_available}>"
