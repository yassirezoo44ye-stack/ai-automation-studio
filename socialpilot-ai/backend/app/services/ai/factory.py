"""Selects and constructs the configured AIProvider from environment
settings (`AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` — see app/core/config.py).

Deliberately not cached as a module-level singleton: constructing an
AnthropicProvider is cheap (just wraps an httpx-backed client), and a
fresh instance per call means tests can flip AI_API_KEY between cases
without fighting an `lru_cache`.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.exceptions import ConfigurationError
from app.services.ai.provider import AIProvider

_SUPPORTED_PROVIDERS = ("anthropic", "mock")


def get_ai_provider() -> AIProvider:
    settings = get_settings()

    # "mock" is the one provider that doesn't need AI_API_KEY — it never
    # calls a real vendor (see mock_provider.py's docstring). Guarded out of
    # production by Settings.validate_for_production() at boot, so this
    # branch existing here can't accidentally serve real users fake content.
    if settings.ai_provider == "mock":
        from app.services.ai.mock_provider import MockAIProvider

        return MockAIProvider()

    if not settings.ai_api_key:
        raise ConfigurationError(
            "AI generation is not configured on this server — set AI_API_KEY (and AI_PROVIDER/AI_MODEL "
            "if not using the defaults) to enable it."
        )
    if settings.ai_provider == "anthropic":
        from app.services.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.ai_api_key, model=settings.ai_model)

    raise ConfigurationError(
        f"Unsupported AI_PROVIDER: {settings.ai_provider!r}. Supported: {', '.join(_SUPPORTED_PROVIDERS)}."
    )
