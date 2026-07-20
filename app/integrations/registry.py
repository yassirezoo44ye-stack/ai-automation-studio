"""
IntegrationRegistry — process-wide catalog of available provider
implementations (not connections; a connection is a per-org row created
by IntegrationService once a provider is registered here).
"""
from __future__ import annotations

import logging

from app.integrations.provider import IntegrationProvider

log = logging.getLogger(__name__)


class IntegrationRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, IntegrationProvider] = {}

    def register(self, provider: IntegrationProvider) -> None:
        if provider.provider_id in self._providers:
            log.warning("integration provider %r re-registered, replacing", provider.provider_id)
        self._providers[provider.provider_id] = provider
        log.info("integration provider registered: %s (%s)", provider.provider_id, provider.provider_type.value)

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def get(self, provider_id: str) -> IntegrationProvider | None:
        return self._providers.get(provider_id)

    def require(self, provider_id: str) -> IntegrationProvider:
        provider = self.get(provider_id)
        if provider is None:
            raise KeyError(f"no integration provider registered for {provider_id!r}")
        return provider

    def list_providers(self) -> list[IntegrationProvider]:
        return list(self._providers.values())


_registry: IntegrationRegistry | None = None


def get_integration_registry() -> IntegrationRegistry:
    global _registry
    if _registry is None:
        _registry = IntegrationRegistry()
    return _registry
