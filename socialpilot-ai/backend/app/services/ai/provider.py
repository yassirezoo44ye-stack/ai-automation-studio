"""AIProvider — the one interface content generation talks to.

No router or service outside this package knows which AI vendor is behind
`get_ai_provider()` (see factory.py), and none of them ever see an API key
— it's read from environment configuration once, inside the concrete
provider, and never persisted or returned to a client.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIGenerationError(Exception):
    """The provider was reachable/configured but the call itself failed
    (rate limit, malformed response, provider-side error, etc.) — distinct
    from ConfigurationError (app/core/exceptions.py), which means the
    provider was never even reachable because nothing is configured."""


class AIProvider(ABC):
    """Subclass once per vendor. `generate_structured` is the primary path
    for Phase 2 (ideas/posts are always schema-validated, never
    free-form-parsed) — `generate` exists for the simpler unstructured case
    a future feature might need."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The concrete model identifier in use — recorded on every
        ContentGeneration row (app/models/content_generation.py) for
        traceability, never guessed at via a private attribute by callers."""

    @abstractmethod
    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        """Free-form text completion."""

    @abstractmethod
    async def generate_structured(
        self, *, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 2048,
    ) -> dict[str, Any] | list[Any]:
        """Completion constrained to `schema` (a JSON Schema object
        describing the exact shape the caller needs). Must raise
        AIGenerationError rather than return a best-effort guess if the
        provider can't/won't produce conforming output."""
