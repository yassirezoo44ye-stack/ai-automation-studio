"""
Model catalog — authoritative list of all known models and their capabilities.

The ModelRouter reads this to make selection decisions. Update this file when
providers release new models or change pricing.

Never hardcode model names anywhere else — always use catalog.get(model_id).
"""
from __future__ import annotations

from dataclasses import dataclass
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
    # Relative scores (0..1) used by policy-driven selection (ModelRouter,
    # CostRouter) — not provider-reported, hand-tuned per generation/tier.
    quality:         float = 0.75
    speed:           float = 0.70

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
        quality=1.00,
        speed=0.45,
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
        quality=0.96,
        speed=0.68,
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
        quality=0.95,
        speed=0.70,
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
        quality=0.82,
        speed=0.92,
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
        quality=0.92,
        speed=0.75,
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
        quality=0.78,
        speed=0.95,
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
        quality=0.90,
        speed=0.65,
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
        quality=0.97,
        speed=0.35,
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
        quality=0.88,
        speed=0.60,
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
        quality=0.93,
        speed=0.55,
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
        quality=0.83,
        speed=0.90,
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
        quality=0.80,
        speed=0.96,
    ),
]

# ── OpenRouter ────────────────────────────────────────────────────────────────
# No app/ai/providers/openrouter.py backend exists yet — ProviderRegistry
# (app/ai/providers/registry.py) only knows anthropic/openai/gemini, so
# selecting this model would fail the whole completion (failover_chain()
# returns empty since "openrouter" isn't in its provider map). deprecated=True
# keeps it out of every ModelCatalog selection method (_candidates() filters
# `not m.deprecated`) without deleting the documented entry. Its $0.0 cost
# would otherwise make CHEAPEST-policy selection pick it automatically.
# Flip deprecated=False once a real provider backend is built.

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
        deprecated=True,
    ),
]

# ── Deferred providers ───────────────────────────────────────────────────────
# DeepSeek, Mistral, Ollama, Azure OpenAI, Amazon Bedrock — catalogued (per
# the AI Routing phase's provider list) so cost/routing tooling can see and
# price them, but NOT wired to a real app/ai/providers/*.py backend.
# deprecated=True is the exact same "not really available" signal used for
# openrouter/auto above — every non-deprecated-model test/guard already
# excludes these. User-confirmed scope decision (this session): honest
# catalog-only stubs, no untested provider implementations ship this phase.
# Pricing/quality/speed carried over from the former app/ai/cost_router.py
# _DEFAULT_MODELS table (now reconciled into this single catalog).

_DEFERRED: list[ModelInfo] = [
    ModelInfo(
        id="deepseek-chat",
        provider_id="deepseek",
        display_name="DeepSeek Chat",
        context_window=64_000,
        output_limit=8_192,
        input_cost_m=0.14,
        output_cost_m=0.28,
        latency_tier="fast",
        deprecated=True,
        quality=0.80,
        speed=0.80,
    ),
    ModelInfo(
        id="mistral-large",
        provider_id="mistral",
        display_name="Mistral Large",
        context_window=128_000,
        output_limit=8_192,
        input_cost_m=2.00,
        output_cost_m=6.00,
        latency_tier="medium",
        deprecated=True,
        quality=0.85,
        speed=0.72,
    ),
    ModelInfo(
        id="mistral-small",
        provider_id="mistral",
        display_name="Mistral Small",
        context_window=32_000,
        output_limit=8_192,
        input_cost_m=0.20,
        output_cost_m=0.60,
        latency_tier="fast",
        deprecated=True,
        quality=0.72,
        speed=0.90,
    ),
    ModelInfo(
        id="ollama/llama3.1",
        provider_id="ollama",
        display_name="Llama 3.1 (Ollama, local)",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=0.0,
        output_cost_m=0.0,
        latency_tier="medium",
        deprecated=True,
        quality=0.65,
        speed=0.60,
    ),
    ModelInfo(
        id="azure/gpt-4o",
        provider_id="azure_openai",
        display_name="GPT-4o (Azure OpenAI)",
        context_window=128_000,
        output_limit=4_096,
        input_cost_m=2.50,
        output_cost_m=10.00,
        supports_vision=True,
        latency_tier="medium",
        deprecated=True,
        quality=0.92,
        speed=0.70,
    ),
    ModelInfo(
        id="bedrock/claude-sonnet",
        provider_id="bedrock",
        display_name="Claude Sonnet (Amazon Bedrock)",
        context_window=200_000,
        output_limit=8_096,
        input_cost_m=3.00,
        output_cost_m=15.00,
        supports_vision=True,
        latency_tier="medium",
        deprecated=True,
        quality=0.94,
        speed=0.65,
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


catalog = ModelCatalog(_ANTHROPIC + _OPENAI + _GEMINI + _OPENROUTER + _DEFERRED)
