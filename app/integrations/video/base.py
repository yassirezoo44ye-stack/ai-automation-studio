"""
VideoProvider — abstract base for AI video generation providers.

Design rationale (matches IntegrationProvider pattern in app/integrations/provider.py):
- Providers are stateless business logic; they never touch the DB directly.
- The Training Studio router manages persistence — the provider just does
  the network call and returns structured data.
- Adding a new provider (HeyGen, Runway, etc.) means subclassing VideoProvider
  and registering it in registry.py; no changes required in the router.

Provider lifecycle for a video:
    1. create_video()   → returns provider_video_id + initial status
    2. get_video_status() → poll until status == "completed"
    3. delete_video()   → clean up remote asset (optional, best-effort)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VideoStatus(str, Enum):
    DRAFT      = "draft"
    QUEUED     = "queued"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


@dataclass
class VideoCreateResult:
    """Returned by VideoProvider.create_video()."""
    provider_video_id: str
    status:            VideoStatus
    url:               str | None          = None
    thumbnail_url:     str | None          = None
    duration_seconds:  int | None          = None
    metadata:          dict[str, Any]      = field(default_factory=dict)


@dataclass
class VideoStatusResult:
    """Returned by VideoProvider.get_video_status()."""
    provider_video_id: str
    status:            VideoStatus
    url:               str | None          = None
    thumbnail_url:     str | None          = None
    duration_seconds:  int | None          = None
    error_message:     str | None          = None
    metadata:          dict[str, Any]      = field(default_factory=dict)


class VideoProvider(ABC):
    """
    Subclass once per video provider (Synthesia, HeyGen, Runway, …).

    All methods are async so implementations can use httpx / aiohttp
    without blocking the event loop. Providers that have no real remote
    (e.g. MockVideoProvider) simply return synchronous values wrapped
    in `return`.
    """

    # ── Identity ─────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable, unique slug — e.g. 'synthesia'. Never changes once shipped."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI — e.g. 'Synthesia'."""

    def is_available(self, config: dict[str, Any]) -> bool:
        """Return True if the provider has the required credentials in config.
        Default: always available (useful for MockVideoProvider in dev)."""
        return True

    # ── Core API ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def create_video(
        self,
        *,
        title:     str,
        script:    str,
        language:  str           = "en",
        avatar_id: str | None    = None,
        voice_id:  str | None    = None,
        config:    dict[str, Any] | None = None,
    ) -> VideoCreateResult:
        """
        Submit a video creation job to the provider.

        Returns immediately with the provider's video ID and initial status.
        For providers where creation is synchronous (e.g. short test clips),
        status may already be COMPLETED on return.

        Raises RuntimeError on network/auth failure — the caller (job worker)
        records the error and marks the training_jobs row as failed.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_video_status(
        self,
        video_id: str,
        config:   dict[str, Any] | None = None,
    ) -> VideoStatusResult:
        """
        Poll the provider for the current status of a video.

        Called by the job worker on a schedule until status is terminal
        (COMPLETED or FAILED).
        """
        raise NotImplementedError

    async def delete_video(
        self,
        video_id: str,
        config:   dict[str, Any] | None = None,
    ) -> None:
        """Best-effort remote cleanup. Default no-op (provider may not support it)."""
        return None
