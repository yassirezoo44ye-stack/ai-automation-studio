"""
AI Cost Router — policy-driven model selection + per-org cost accounting.

Given a request profile (estimated tokens, quality floor, latency budget) and
a routing policy, picks the best model and produces a cost prediction plus an
ordered fallback chain. Also accumulates actual spend per organization/
project/workflow/agent/user (see track_cost/costs_for_org).

AI Routing consolidation: this used to carry its own _DEFAULT_MODELS price
table that disagreed with app/core/ai/models/catalog.py (e.g. gpt-4o priced
$2.50/$10 here vs $5/$15 there) — two pricing tables for the same models.
Now reads model data (pricing, quality, speed, context) from that single
catalog — the same one app/core/ai/router/model_router.py's ModelRouter
already uses for live provider selection in InferenceEngine. One catalog,
one set of numbers, everywhere.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

from app.core.ai.models.catalog import ModelInfo, catalog as model_catalog

log = logging.getLogger(__name__)


class Policy(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST  = "fastest"
    QUALITY  = "quality"
    BALANCED = "balanced"
    CUSTOM   = "custom"


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
    """Policy-driven model selection + per-org cost accounting."""

    def __init__(self) -> None:
        # Per-instance availability overrides (model_id -> bool), layered on
        # top of the shared catalog's deprecated flag — lets ops disable a
        # real provider at runtime without mutating the shared catalog
        # (ModelInfo is frozen/shared across every CostRouter instance).
        self._availability_overrides: dict[str, bool] = {}
        # In-process cost ledger: (org_id, scope_type, scope_id) -> usd
        self._ledger: dict[tuple[str, str, str], float] = {}
        self._decisions: list[dict[str, Any]] = []  # last N routing decisions

    # ── Catalog access ────────────────────────────────────────────────────────

    def _is_available(self, m: ModelInfo) -> bool:
        return self._availability_overrides.get(m.id, not m.deprecated)

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": m.id,
                "provider": m.provider_id,
                "display_name": m.display_name,
                "input_per_m": m.input_cost_m,
                "output_per_m": m.output_cost_m,
                "quality": m.quality,
                "speed": m.speed,
                "context_window": m.context_window,
                "available": self._is_available(m),
            }
            for m in model_catalog.all()
        ]

    def set_availability(self, model_id: str, available: bool) -> None:
        if model_catalog.get(model_id) is None:
            raise KeyError(model_id)
        self._availability_overrides[model_id] = available

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, req: RouteRequest) -> RouteDecision:
        candidates = [
            m for m in model_catalog.all()
            if self._is_available(m)
            and m.quality >= req.min_quality
            and m.context_window >= req.required_context
            and m.provider_id not in req.exclude_providers
        ]
        if req.max_cost_usd is not None:
            candidates = [
                m for m in candidates
                if m.estimate_cost(req.est_input_tokens, req.est_output_tokens) <= req.max_cost_usd
            ]
        if not candidates:
            raise LookupError("no model satisfies the routing constraints")

        scored = sorted(candidates, key=lambda m: self._score(m, req), reverse=True)
        best = scored[0]
        decision = RouteDecision(
            model=best.id,
            provider=best.provider_id,
            predicted_cost_usd=round(best.estimate_cost(req.est_input_tokens, req.est_output_tokens), 6),
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

    def _score(self, m: ModelInfo, req: RouteRequest) -> float:
        cost = m.estimate_cost(req.est_input_tokens, req.est_output_tokens)
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
    def _reason(m: ModelInfo, req: RouteRequest) -> str:
        return (
            f"policy={req.policy.value}: {m.id} "
            f"(quality={m.quality}, speed={m.speed}, "
            f"est=${m.estimate_cost(req.est_input_tokens, req.est_output_tokens):.4f})"
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
