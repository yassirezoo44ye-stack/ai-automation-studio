"""
Minimal provider ABCs for the three plugin types that have NO existing
extension point anywhere in this codebase (confirmed by direct reads):
conversation memory is hardcoded to Postgres (app/ai/memory.py), agent
memory is hardcoded to a local JSON file (app/agents/memory.py), OAuth
providers are hardcoded per-vendor in the auth router with no shared
interface, and file/object storage has no abstraction at all.

These ABCs plus the registries in app/plugins/registry.py let a plugin
REGISTER an alternative implementation. Actually routing platform code
through a registered provider (e.g. making conversation history load via
whatever MemoryProvider is registered, instead of always querying Postgres
directly) would mean modifying those core modules — out of scope for this
phase ("do not modify unrelated systems"). This is real, usable
infrastructure with no platform consumer yet, the same "declared, not yet
wired everywhere" pattern the Marketplace phase used for its security stub
hooks — a future phase can thread these through app/ai/memory.py,
app/routers/auth_users.py, etc. without changing this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class MemoryProviderBase(ABC):
    """Alternative backend for conversational/agent memory."""

    @abstractmethod
    async def load(self, scope_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def append(self, scope_id: str, entry: dict[str, Any]) -> None: ...

    @abstractmethod
    async def clear(self, scope_id: str) -> None: ...


class StorageProviderBase(ABC):
    """Alternative backend for file/blob storage."""

    @abstractmethod
    async def put(self, path: str, data: bytes) -> str:
        """Returns a reference (URL or opaque id) to the stored object."""

    @abstractmethod
    async def get(self, ref: str) -> Optional[bytes]: ...

    @abstractmethod
    async def delete(self, ref: str) -> bool: ...


class AuthProviderBase(ABC):
    """Alternative OAuth/SSO identity provider."""

    provider_id: str

    @abstractmethod
    def get_authorization_url(self, *, redirect_uri: str, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        """Returns a normalized user-profile dict: at minimum {email, name}."""
