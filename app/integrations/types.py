"""
Core types shared across the Integration SDK. No provider-specific code
lives here — this module only defines the vocabulary every provider,
the registry, and the service layer agree on.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ProviderType(str, Enum):
    """The authentication shape a provider uses. A provider's `connect()`
    contract differs by type (see oauth.py for OAUTH2's flow), but every
    type produces the same IntegrationCredential shape at rest."""
    OAUTH2     = "oauth2"
    API_KEY    = "api_key"
    JWT        = "jwt"
    BASIC_AUTH = "basic_auth"
    CUSTOM     = "custom"


class IntegrationStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED    = "connected"
    SYNCING      = "syncing"
    ERROR        = "error"
    DEGRADED     = "degraded"   # connected, but the circuit breaker has seen recent failures


class SyncStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"


@dataclass
class ProviderCapabilities:
    """What a provider declares it can do — the registry and permission
    model both read this; a provider that doesn't declare `webhooks` never
    gets a webhook URL issued, one that doesn't declare `sync` is exempt
    from the sync engine's scheduling loop, etc."""
    sync: bool = False
    webhooks: bool = False
    background_jobs: bool = False
    real_time: bool = False


@dataclass
class ProviderScope:
    """One permission a connection can request, e.g. `read:messages`.
    Purely descriptive at the SDK layer — enforcement is the caller's
    responsibility via permissions.py's approval gate."""
    id: str
    label: str
    sensitive: bool = False


@dataclass
class IntegrationCredential:
    """The decrypted, in-memory shape a provider's connect()/sync()/
    handle_webhook() methods receive. Never serialized as-is — the
    credential store only ever persists the encrypted form (see
    credential_store.py)."""
    provider_id: str
    organization_id: str
    provider_type: ProviderType
    secrets: dict[str, str] = field(default_factory=dict)   # e.g. {"access_token": "..."}
    metadata: dict[str, Any] = field(default_factory=dict)  # e.g. {"account_email": "..."}
    expires_at: Optional[float] = None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at


@dataclass
class WebhookEvent:
    id: str
    provider_id: str
    organization_id: str
    headers: dict[str, str]
    body: bytes
    received_at: float = field(default_factory=time.time)


@dataclass
class SyncResult:
    status: SyncStatus
    items_synced: int = 0
    message: str = ""
    cursor: Optional[str] = None   # opaque provider-defined position for incremental sync


def new_id() -> str:
    return str(uuid.uuid4())
