"""
AI Cost Router — intelligent model selection across providers.

Given a request profile (estimated tokens, quality floor, latency budget) and
a routing policy, picks the best model from the catalog and produces a cost
prediction plus an ordered fallback chain.

Catalog prices are USD per 1M tokens and are intentionally conservative
snapshots; ops can override at runtime via update_model() or the API.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)


class Provider(str, Enum):
    OPENAI    = "openai"
    ANTHROPIC = "anthropic"
    GEMINI    = "gemini"
    DEEPSEEK  = "deepseek"
    MISTRAL   = "mistral"
    OLLAMA    = "ollama"
    AZURE     = "azure_openai"
    BEDROCK   = "bedrock"


class Policy(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST  = "fastest"
    QUALITY  = "quality"
    BALANCED = "balanced"
    CUSTOM   = "custom"


@dataclass
class ModelSpec:
    id: str
    provider: Provider
    input_per_m: float      # USD / 1M input tokens
    output_per_m: float     # USD / 1M output tokens
    quality: float          # 0..1 relative quality score
    speed: float            # 0..1 relative speed score (1 = fastest)
    context_window: int
    available: bool = True

    def cost(self, in_tokens: int, out_tokens: int) -> float:
        return (in_tokens * self.input_per_m + out_tokens * self.output_per_m) / 1_000_000


# ── Default catalog ───────────────────────────────────────────────────────────

_DEFAULT_MODELS: list[ModelSpec] = [
    # Anthropic
    ModelSpec("claude-sonnet-4-6",    Provider.ANTHROPIC, 3.00, 15.00, 0.95, 0.70, 200_000),
    ModelSpec("claude-haiku-4-5",     Provider.ANTHROPIC, 0.80,  4.00, 0.82, 0.92, 200_000),
    ModelSpec("claude-opus-4-8",      Provider.ANTHROPIC, 15.00, 75.00, 1.00, 0.45, 200_000),
    # OpenAI
    ModelSpec("gpt-4o",               Provider.OPENAI,    2.50, 10.00, 0.92, 0.75, 128_000),
    ModelSpec("gpt-4o-mini",          Provider.OPENAI,    0.15,  0.60, 0.78, 0.95, 128_000),
    # Google
    ModelSpec("gemini-2.0-flash",     Provider.GEMINI,    0.10,  0.40, 0.80, 0.96, 1_000_000),
    ModelSpec("gemini-2.0-pro",       Provider.GEMINI,    1.25,  5.00, 0.90, 0.70, 2_000_000),
    # DeepSeek, Mistral, Ollama, Azure, Bedrock — catalogued for future work
    # but NOT wired to a real app/ai/providers/*.py backend yet. available=False
    # keeps them out of route() candidate selection so /api/ai/route never
    # hands back a "decision" that fails at execution. Flip to True only once
    # a matching provider file exists in app/ai/providers/.
    ModelSpec("deepseek-chat",        Provider.DEEPSEEK,  0.14,  0.28, 0.80, 0.80, 64_000, available=False),
    ModelSpec("mistral-large",        Provider.MISTRAL,   2.00,  6.00, 0.85, 0.72, 128_000, available=False),
    ModelSpec("mistral-small",        Provider.MISTRAL,   0.20,  0.60, 0.72, 0.90, 32_000, available=False),
    ModelSpec("ollama/llama3.1",      Provider.OLLAMA,    0.00,  0.00, 0.65, 0.60, 128_000, available=False),
    ModelSpec("azure/gpt-4o",         Provider.AZURE,     2.50, 10.00, 0.92, 0.70, 128_000, available=False),
    ModelSpec("bedrock/claude-sonnet", Provider.BEDROCK,  3.00, 15.00, 0.94, 0.65, 200_000, available=False),
]


@dataclass
class RouteRequest:
    est_input_tokens: int = 1_000
    est_output_tokens: int = 1_000
    min_quality: float = 0.0
    max_cost_usd: float | None = None
    required_context: int = 0
    exclude_providers: tuple[str, ...] = ()
    policy: Policy = Policy.BALANCED
    custom_weights: dict[str, float] = field(default_factory=dict)  # cost/quality/speed


@dataclass
class RouteDecision:
    model: str
    provider: str
    predicted_cost_usd: float
    quality: float
    speed: float
    fallbacks: list[str]
    policy: str
    reason: str


class CostRouter:
    """Model catalog + policy-driven selection + per-org cost accounting."""

    def __init__(self, models: list[ModelSpec] | None = None):
        self._models: dict[str, ModelSpec] = {m.id: m for m in (models or list(_DEFAULT_MODELS))}
        # In-process cost ledger: (org_id, scope_type, scope_id) -> usd
        self._ledger: dict[tuple[str, str, str], float] = {}
        self._decisions: list[dict[str, Any]] = []  # last N routing decisions

    # ── Catalog management ────────────────────────────────────────────────────

    def list_models(self) -> list[dict[str, Any]]:
        return [asdict(m) for m in self._models.values()]

    def update_model(self, model_id: str, **fields: Any) -> None:
        spec = self._models.get(model_id)
        if spec is None:
            raise KeyError(model_id)
        for k, v in fields.items():
            if hasattr(spec, k):
                setattr(spec, k, v)

    def set_availability(self, model_id: str, available: bool) -> None:
        self.update_model(model_id, available=available)

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, req: RouteRequest) -> RouteDecision:
        candidates = [
            m for m in self._models.values()
            if m.available
            and m.quality >= req.min_quality
            and m.context_window >= req.required_context
            and m.provider.value not in req.exclude_providers
        ]
        if req.max_cost_usd is not None:
            candidates = [
                m for m in candidates
                if m.cost(req.est_input_tokens, req.est_output_tokens) <= req.max_cost_usd
            ]
        if not candidates:
            raise LookupError("no model satisfies the routing constraints")

        scored = sorted(candidates, key=lambda m: self._score(m, req), reverse=True)
        best = scored[0]
        decision = RouteDecision(
            model=best.id,
            provider=best.provider.value,
            predicted_cost_usd=round(best.cost(req.est_input_tokens, req.est_output_tokens), 6),
            quality=best.quality,
            speed=best.speed,
            fallbacks=[m.id for m in scored[1:4]],
            policy=req.policy.value,
            reason=self._reason(best, req),
        )
        self._decisions.append({**asdict(decision), "ts": time.time()})
        if len(self._decisions) > 500:
            self._decisions = self._decisions[-250:]
        return decision

    def _score(self, m: ModelSpec, req: RouteRequest) -> float:
        cost = m.cost(req.est_input_tokens, req.est_output_tokens)
        # Normalise cost to 0..1 (cheaper = higher). $1 per call ≈ 0.
        cost_score = max(0.0, 1.0 - min(cost, 1.0))
        if req.policy == Policy.CHEAPEST:
            w = {"cost": 0.85, "quality": 0.10, "speed": 0.05}
        elif req.policy == Policy.FASTEST:
            w = {"cost": 0.05, "quality": 0.15, "speed": 0.80}
        elif req.policy == Policy.QUALITY:
            w = {"cost": 0.05, "quality": 0.85, "speed": 0.10}
        elif req.policy == Policy.CUSTOM and req.custom_weights:
            w = {"cost": 0.34, "quality": 0.33, "speed": 0.33, **req.custom_weights}
        else:  # BALANCED
            w = {"cost": 0.35, "quality": 0.40, "speed": 0.25}
        return cost_score * w["cost"] + m.quality * w["quality"] + m.speed * w["speed"]

    @staticmethod
    def _reason(m: ModelSpec, req: RouteRequest) -> str:
        return (
            f"policy={req.policy.value}: {m.id} "
            f"(quality={m.quality}, speed={m.speed}, "
            f"est=${m.cost(req.est_input_tokens, req.est_output_tokens):.4f})"
        )

    # ── Cost accounting ───────────────────────────────────────────────────────

    def track_cost(
        self, org_id: str, usd: float, *,
        scope_type: str = "org", scope_id: str = "",
    ) -> None:
        """Accumulate actual spend per organization/project/workflow/agent/user."""
        key = (org_id, scope_type, scope_id or org_id)
        self._ledger[key] = self._ledger.get(key, 0.0) + usd

    def costs_for_org(self, org_id: str) -> dict[str, Any]:
        by_scope: dict[str, dict[str, float]] = {}
        total = 0.0
        for (oid, stype, sid), usd in self._ledger.items():
            if oid != org_id:
                continue
            by_scope.setdefault(stype, {})[sid] = round(usd, 6)
            total += usd
        return {"organization_id": org_id, "total_usd": round(total, 6), "by_scope": by_scope}

    def recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._decisions[-limit:][::-1]


# ── Singleton wiring ──────────────────────────────────────────────────────────

_router: Optional[CostRouter] = None


def get_cost_router() -> CostRouter:
    global _router
    if _router is None:
        _router = CostRouter()
    return _router
