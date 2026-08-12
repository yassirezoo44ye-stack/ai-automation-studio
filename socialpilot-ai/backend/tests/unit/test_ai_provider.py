from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.schemas.content import GENERATED_IDEAS_JSON_SCHEMA, GENERATED_POST_JSON_SCHEMA
from app.services.ai.factory import get_ai_provider
from app.services.ai.mock_provider import MockAIProvider


class TestMockProvider:
    async def test_generate_structured_ideas_matches_schema_shape(self) -> None:
        provider = MockAIProvider()
        result = await provider.generate_structured(system="", prompt="", schema=GENERATED_IDEAS_JSON_SCHEMA)
        assert "ideas" in result
        assert len(result["ideas"]) >= 1
        for idea in result["ideas"]:
            for key in ("title", "hook", "concept", "pillar", "suggested_platform", "cta"):
                assert key in idea and idea[key]

    async def test_generate_structured_post_matches_schema_shape(self) -> None:
        provider = MockAIProvider()
        result = await provider.generate_structured(system="", prompt="", schema=GENERATED_POST_JSON_SCHEMA)
        for key in ("hook", "body", "cta", "hashtags", "platform", "media_concept"):
            assert key in result

    async def test_generate_returns_deterministic_text(self) -> None:
        provider = MockAIProvider()
        first = await provider.generate(system="x", prompt="y")
        second = await provider.generate(system="x", prompt="y")
        assert first == second  # deterministic, not a real model call

    def test_model_name_identifies_itself_as_mock(self) -> None:
        assert "mock" in MockAIProvider().model_name.lower()


class TestFactory:
    def test_mock_provider_selected_without_api_key(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "mock")
        monkeypatch.delenv("AI_API_KEY", raising=False)
        from app.core.config import get_settings

        get_settings.cache_clear()
        try:
            provider = get_ai_provider()
            assert isinstance(provider, MockAIProvider)
        finally:
            get_settings.cache_clear()

    def test_missing_api_key_raises_configuration_error(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.delenv("AI_API_KEY", raising=False)
        from app.core.config import get_settings

        get_settings.cache_clear()
        try:
            with pytest.raises(ConfigurationError):
                get_ai_provider()
        finally:
            get_settings.cache_clear()

    def test_unsupported_provider_raises_configuration_error(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "some-vendor-nobody-implemented")
        monkeypatch.setenv("AI_API_KEY", "sk-whatever")
        from app.core.config import get_settings

        get_settings.cache_clear()
        try:
            with pytest.raises(ConfigurationError):
                get_ai_provider()
        finally:
            get_settings.cache_clear()


class TestProductionGuardsAgainstMockProvider:
    def test_mock_provider_rejected_in_production(self) -> None:
        settings = Settings(
            environment="production", jwt_secret_key="a" * 40, cookie_secure=True, ai_provider="mock",
        )
        with pytest.raises(RuntimeError, match="AI_PROVIDER=mock"):
            settings.validate_for_production()

    def test_mock_provider_allowed_outside_production(self) -> None:
        settings = Settings(environment="development", ai_provider="mock")
        settings.validate_for_production()  # must not raise
