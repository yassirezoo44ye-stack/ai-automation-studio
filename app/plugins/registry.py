"""
Registries for the three plugin types that have no existing platform
registry to plug into (see provider_types.py's docstring for why). Each is
a simple named dict — same shape as app.ai.providers.registry's `_ALL`,
just three of them instead of one, since these are unrelated concerns.
"""
from __future__ import annotations

import logging

from app.plugins.provider_types import AuthProviderBase, MemoryProviderBase, StorageProviderBase

log = logging.getLogger(__name__)

_MEMORY_PROVIDERS : dict[str, MemoryProviderBase]  = {}
_STORAGE_PROVIDERS: dict[str, StorageProviderBase] = {}
_AUTH_PROVIDERS   : dict[str, AuthProviderBase]    = {}


def register_memory_provider(provider_id: str, provider: MemoryProviderBase) -> None:
    _MEMORY_PROVIDERS[provider_id] = provider
    log.info("registered memory provider: %s", provider_id)


def unregister_memory_provider(provider_id: str) -> bool:
    return _MEMORY_PROVIDERS.pop(provider_id, None) is not None


def get_memory_provider(provider_id: str) -> MemoryProviderBase | None:
    return _MEMORY_PROVIDERS.get(provider_id)


def register_storage_provider(provider_id: str, provider: StorageProviderBase) -> None:
    _STORAGE_PROVIDERS[provider_id] = provider
    log.info("registered storage provider: %s", provider_id)


def unregister_storage_provider(provider_id: str) -> bool:
    return _STORAGE_PROVIDERS.pop(provider_id, None) is not None


def get_storage_provider(provider_id: str) -> StorageProviderBase | None:
    return _STORAGE_PROVIDERS.get(provider_id)


def register_auth_provider(provider_id: str, provider: AuthProviderBase) -> None:
    _AUTH_PROVIDERS[provider_id] = provider
    log.info("registered auth provider: %s", provider_id)


def unregister_auth_provider(provider_id: str) -> bool:
    return _AUTH_PROVIDERS.pop(provider_id, None) is not None


def get_auth_provider(provider_id: str) -> AuthProviderBase | None:
    return _AUTH_PROVIDERS.get(provider_id)
