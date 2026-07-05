"""
Model catalog — authoritative list of all known models and their capabilities.

The ModelRouter reads this to make selection decisions. Update this file when
providers release new models or change pricing.

Never hardcode model names anywhere else — always use catalog.get(model_id).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ModelInfo:
    id:              str
    provider_id:     str
    display_name:    str
    context_window:  int           # max input tokens
    output_limit:    int           # max output tokens
    input_cost_m:    float         # USD per million input tokens
    output_cost_m:   float         # USD per million output tokens
    supports_tools:  bool = True
    supports_stream: bool = True
    supports_vision: bool = False
    reasoning:       bool = False  # chain-of-thought / extended thinking
    latency_tier:    str  = "medium"  # "fast" | "medium" | "slow"
    deprecated:      bool = False

    @property
    def input_cost_per_token(self) -> float:
        return self.input_cost_m / 1_000_000

    @property
    def output_cost_per_token(self) -> float:
        return self.output_cost_m / 1_000_000

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens * self.input_cost_per_token
            + output_tokens * self.output_cost_per_token,
            8,
        )


# ── Anthropic ─────────────────────────────────────────────────────────────────

_ANTHROPIC: list[ModelInfo] = [
    ModelInfo(
        id="claude-opus-4-8",
        provider_id="anthropic",
        display_name="Claude Opus 4.8",
        context_window=200_000,
        output_limit=32_000,
        input_cost_m=15.0,
        output_cost_m=75.0,
        supports_vision=True,
        reasoning=True,
        latency_tier="slow",
    ),
    ModelInfo(
        id="claude-sonnet-5",
        provider_id="anthropic",
        display_name="Claude Sonnet 5",
        context_window=200_000,
        output_limit=16_000,
        input_cost_m=3.0,
        output_cost_m=15.0,
        supports_vision=True,
        latency_tier="medium",
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        provider_id="anthropic",
        display_name="Claude Sonnet 4.6",
        context_window=200_000,
        output_limit=8_096,
        input_cost_m=3.0,
        output_cost_m=15.0,
        supports_vision=True,
        latency_tier="medium",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        provider_id="anthropic",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        output_limit=8_096,
        input_cost_m=0.25,
        output_cost_m=1.25,
        latency_tier="fast",
    ),
]

# ── OpenAI ────────────────────────────────────────────────────────────────────

_OPENAI: list[ModelInfo] = [
    ModelInfo(
        id="gpt-4o",
        provider_id="openai",
        display_name="GPT-4o",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=5.0,
        output_cost_m=15.0,
        supports_vision=True,
        latency_tier="medium",
    ),
    ModelInfo(
        id="gpt-4o-mini",
        provider_id="openai",
        display_name="GPT-4o Mini",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=0.15,
        output_cost_m=0.6,
        latency_tier="fast",
    ),
    ModelInfo(
        id="gpt-4-turbo",
        provider_id="openai",
        display_name="GPT-4 Turbo",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=10.0,
        output_cost_m=30.0,
        supports_vision=True,
        latency_tier="medium",
    ),
    ModelInfo(
        id="o3",
        provider_id="openai",
        display_name="o3",
        context_window=200_000,
        output_limit=100_000,
        input_cost_m=10.0,
        output_cost_m=40.0,
        reasoning=True,
        latency_tier="slow",
    ),
    ModelInfo(
        id="o4-mini",
        provider_id="openai",
        display_name="o4-mini",
        context_window=200_000,
        output_limit=100_000,
        input_cost_m=1.1,
        output_cost_m=4.4,
        reasoning=True,
        latency_tier="medium",
    ),
]

# ── Google Gemini ─────────────────────────────────────────────────────────────

_GEMINI: list[ModelInfo] = [
    ModelInfo(
        id="gemini-2.5-pro",
        provider_id="gemini",
        display_name="Gemini 2.5 Pro",
        context_window=2_000_000,
        output_limit=65_536,
        input_cost_m=1.25,
        output_cost_m=10.0,
        supports_vision=True,
        reasoning=True,
        latency_tier="slow",
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        provider_id="gemini",
        display_name="Gemini 2.5 Flash",
        context_window=1_000_000,
        output_limit=65_536,
        input_cost_m=0.075,
        output_cost_m=0.3,
        latency_tier="fast",
    ),
    ModelInfo(
        id="gemini-2.0-flash",
        provider_id="gemini",
        display_name="Gemini 2.0 Flash",
        context_window=1_000_000,
        output_limit=8_192,
        input_cost_m=0.1,
        output_cost_m=0.4,
        latency_tier="fast",
    ),
]

# ── OpenRouter ────────────────────────────────────────────────────────────────

_OPENROUTER: list[ModelInfo] = [
    ModelInfo(
        id="openrouter/auto",
        provider_id="openrouter",
        display_name="OpenRouter Auto",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=0.0,
        output_cost_m=0.0,
        latency_tier="medium",
    ),
]


# ── Catalog ───────────────────────────────────────────────────────────────────

class ModelCatalog:
    """
    Central registry of known models.

    Access via the module-level singleton `catalog`.
    """

    def __init__(self, models: list[ModelInfo]) -> None:
        self._by_id: dict[str, ModelInfo] = {m.id: m for m in models}
        self._by_provider: dict[str, list[ModelInfo]] = {}
        for m in models:
            self._by_provider.setdefault(m.provider_id, []).append(m)

    def get(self, model_id: str) -> Optional[ModelInfo]:
        return self._by_id.get(model_id)

    def for_provider(self, provider_id: str) -> list[ModelInfo]:
        return self._by_provider.get(provider_id, [])

    def all(self) -> list[ModelInfo]:
        return list(self._by_id.values())

    def cheapest(
        self,
        *,
        provider_id: Optional[str] = None,
        min_context: int = 0,
        requires_tools: bool = False,
        requires_vision: bool = False,
    ) -> Optional[ModelInfo]:
        candidates = self._candidates(
            provider_id=provider_id,
            min_context=min_context,
            requires_tools=requires_tools,
            requires_vision=requires_vision,
        )
        return min(candidates, key=lambda m: m.input_cost_m, default=None)

    def fastest(
        self,
        *,
        provider_id: Optional[str] = None,
        min_context: int = 0,
        requires_tools: bool = False,
    ) -> Optional[ModelInfo]:
        order = {"fast": 0, "medium": 1, "slow": 2}
        candidates = self._candidates(
            provider_id=provider_id,
            min_context=min_context,
            requires_tools=requires_tools,
        )
        return min(candidates, key=lambda m: order.get(m.latency_tier, 9), default=None)

    def most_capable(
        self,
        *,
        provider_id: Optional[str] = None,
    ) -> Optional[ModelInfo]:
        # Proxy: largest context × highest output cost (expensive = capable)
        candidates = [m for m in self._by_id.values()
                      if not m.deprecated
                      and (provider_id is None or m.provider_id == provider_id)]
        return max(candidates, key=lambda m: (m.context_window, m.output_cost_m), default=None)

    def _candidates(
        self,
        *,
        provider_id: Optional[str],
        min_context: int,
        requires_tools: bool = False,
        requires_vision: bool = False,
    ) -> list[ModelInfo]:
        return [
            m for m in self._by_id.values()
            if not m.deprecated
            and (provider_id is None or m.provider_id == provider_id)
            and m.context_window >= min_context
            and (not requires_tools  or m.supports_tools)
            and (not requires_vision or m.supports_vision)
        ]


catalog = ModelCatalog(_ANTHROPIC + _OPENAI + _GEMINI + _OPENROUTER)
