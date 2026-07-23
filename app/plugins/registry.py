"""
Registries for the three plugin types that have no existing platform
registry to plug into (see provider_types.py's docstring for why). Each is
a simple named dict — same shape as app.ai.providers.registry's `_ALL`,
just three of them instead of one, since these are unrelated concerns.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.plugins.provider_types import AuthProviderBase, MemoryProviderBase, StorageProviderBase
from app.plugins.registry_guard import OwnershipTracker

log = logging.getLogger(__name__)

_MEMORY_PROVIDERS : dict[str, MemoryProviderBase]  = {}
_STORAGE_PROVIDERS: dict[str, StorageProviderBase] = {}
_AUTH_PROVIDERS   : dict[str, AuthProviderBase]    = {}

# See app.plugins.registry_guard's module docstring — without these, one
# org's plugin can silently hijack another org's provider_id.
_memory_owners  = OwnershipTracker("memory provider")
_storage_owners = OwnershipTracker("storage provider")
_auth_owners    = OwnershipTracker("auth provider")


def register_memory_provider(provider_id: str, provider: MemoryProviderBase, *, owner: Optional[str] = None) -> None:
    _memory_owners.claim(provider_id, owner)
    _MEMORY_PROVIDERS[provider_id] = provider
    log.info("registered memory provider: %s (owner=%s)", provider_id, owner)


def unregister_memory_provider(provider_id: str) -> bool:
    _memory_owners.release(provider_id)
    return _MEMORY_PROVIDERS.pop(provider_id, None) is not None


def get_memory_provider(provider_id: str) -> MemoryProviderBase | None:
    return _MEMORY_PROVIDERS.get(provider_id)


def register_storage_provider(provider_id: str, provider: StorageProviderBase, *, owner: Optional[str] = None) -> None:
    _storage_owners.claim(provider_id, owner)
    _STORAGE_PROVIDERS[provider_id] = provider
    log.info("registered storage provider: %s (owner=%s)", provider_id, owner)


def unregister_storage_provider(provider_id: str) -> bool:
    _storage_owners.release(provider_id)
    return _STORAGE_PROVIDERS.pop(provider_id, None) is not None


def get_storage_provider(provider_id: str) -> StorageProviderBase | None:
    return _STORAGE_PROVIDERS.get(provider_id)


def register_auth_provider(provider_id: str, provider: AuthProviderBase, *, owner: Optional[str] = None) -> None:
    _auth_owners.claim(provider_id, owner)
    _AUTH_PROVIDERS[provider_id] = provider
    log.info("registered auth provider: %s (owner=%s)", provider_id, owner)


def unregister_auth_provider(provider_id: str) -> bool:
    _auth_owners.release(provider_id)
    return _AUTH_PROVIDERS.pop(provider_id, None) is not None


def get_auth_provider(provider_id: str) -> AuthProviderBase | None:
    return _AUTH_PROVIDERS.get(provider_id)
