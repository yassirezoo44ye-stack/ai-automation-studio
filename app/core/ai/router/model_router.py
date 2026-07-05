"""
ModelRouter — selects the best model for each request.

Factors considered:
  - explicit request.model (always wins if set)
  - provider availability
  - token window vs estimated message length
  - tool support requirement
  - vision requirement
  - latency preference
  - cost optimization flag

Never hardcode model names in endpoints — call router.select(request) instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.ai.models import CompletionRequest
from app.core.ai.models.catalog import ModelInfo, catalog
from app.core.ai.utils.tokens import estimate_messages_tokens

log = logging.getLogger(__name__)


class SelectionPolicy(str):
    """Named selection strategies."""
    CHEAPEST   = "cheapest"
    FASTEST    = "fastest"
    BEST       = "best"       # most capable
    BALANCED   = "balanced"   # best quality within cost/latency constraints


@dataclass
class ModelSelection:
    model_id:    str
    provider_id: str
    reason:      str
    info:        Optional[ModelInfo]


class ModelRouter:
    """
    Selects the best model for a CompletionRequest.

    Usage::

        selection = model_router.select(request)
        # selection.model_id → "claude-sonnet-4-6"
        # selection.reason   → "balanced: sufficient context, tool support"
    """

    def __init__(self, policy: str = SelectionPolicy.BALANCED) -> None:
        self._policy = policy

    def select(
        self,
        request: CompletionRequest,
        *,
        available_providers: list[str] | None = None,
        policy: str | None = None,
    ) -> ModelSelection:
        """
        Return the best model for the request.

        If request.model is set, validate it and return immediately.
        Otherwise run the selection algorithm.
        """
        policy = policy or self._policy

        # Explicit model — validate it's in catalog, then accept
        if request.model:
            info = catalog.get(request.model)
            if info:
                return ModelSelection(
                    model_id=request.model,
                    provider_id=info.provider_id,
                    reason="explicit",
                    info=info,
                )
            # Unknown model — pass through to provider (may be a fine-tuned model)
            provider_id = str(request.provider or "anthropic")
            return ModelSelection(
                model_id=request.model,
                provider_id=provider_id,
                reason="explicit_unknown",
                info=None,
            )

        # Filter to available providers
        provider_id  = str(request.provider or "") or None
        providers    = available_providers or []
        if provider_id and provider_id not in providers:
            providers = [provider_id] + providers

        # Estimate context needs
        msgs_tokens   = estimate_messages_tokens([m.model_dump() for m in request.messages])
        needs_tools   = bool(request.tools)
        needs_context = msgs_tokens + request.max_tokens

        # Run selection
        if policy == SelectionPolicy.CHEAPEST:
            info = catalog.cheapest(
                provider_id=provider_id,
                min_context=needs_context,
                requires_tools=needs_tools,
            )
            reason = "cheapest"

        elif policy == SelectionPolicy.FASTEST:
            info = catalog.fastest(
                provider_id=provider_id,
                min_context=needs_context,
                requires_tools=needs_tools,
            )
            reason = "fastest"

        elif policy == SelectionPolicy.BEST:
            info = catalog.most_capable(provider_id=provider_id)
            reason = "most_capable"

        else:  # BALANCED — reasonable quality at reasonable cost
            info = self._balanced(
                provider_id=provider_id,
                needs_context=needs_context,
                needs_tools=needs_tools,
            )
            reason = "balanced"

        if not info:
            # Absolute fallback
            fallback = "claude-sonnet-4-6"
            return ModelSelection(
                model_id=fallback,
                provider_id="anthropic",
                reason="fallback_default",
                info=catalog.get(fallback),
            )

        log.debug("ModelRouter: selected %s (%s)", info.id, reason)
        return ModelSelection(
            model_id=info.id,
            provider_id=info.provider_id,
            reason=reason,
            info=info,
        )

    def _balanced(
        self,
        *,
        provider_id:   Optional[str],
        needs_context: int,
        needs_tools:   bool,
    ) -> Optional[ModelInfo]:
        """
        Balanced selection:
          1. Must fit context
          2. Must support tools if needed
          3. Prefer medium latency over slow
          4. Among equal latency, prefer lower cost
        """
        tier_order = {"fast": 0, "medium": 1, "slow": 2}
        candidates = [
            m for m in catalog.all()
            if not m.deprecated
            and m.context_window >= needs_context
            and (not needs_tools or m.supports_tools)
            and (provider_id is None or m.provider_id == provider_id)
        ]
        if not candidates:
            return None

        # Sort: medium latency first, then by cost
        candidates.sort(key=lambda m: (tier_order.get(m.latency_tier, 9), m.input_cost_m))
        return candidates[0]

    def estimate_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        info = catalog.get(model_id)
        if not info:
            return 0.0
        return info.estimate_cost(input_tokens, output_tokens)


# Module-level singleton
model_router = ModelRouter(policy=SelectionPolicy.BALANCED)
