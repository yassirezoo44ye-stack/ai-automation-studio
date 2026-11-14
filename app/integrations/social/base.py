"""
SocialPublisherProvider — abstract base for social video publishing.

Design rationale
────────────────
• Mirrors VideoProvider (app/integrations/video/base.py) in structure but
  serves a fundamentally different purpose: publishing user-owned video content
  to social platforms, not generating AI video from a script.
• Providers are stateless: they receive a fully-resolved PublishRequest
  (video URL, caption, account credentials) and return a structured result.
  The router (social_publisher.py) owns all DB interaction.
• Phase 1: URL-based delivery only.  The caller is responsible for ensuring
  video_url is publicly accessible for the duration of the upload.
• Phase 2+: add upload_chunk() for binary resumable uploads.

Adding a new platform:
    1. Subclass SocialPublisherProvider in its own module (e.g. tiktok.py)
    2. Import and register in registry.py
    3. Done — the router never imports platform modules directly
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Status enum ───────────────────────────────────────────────────────────────

class PublishStatus(str, Enum):
    QUEUED      = "queued"
    PROCESSING  = "processing"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


# ── Data transfer objects ─────────────────────────────────────────────────────

@dataclass
class PublishRequest:
    """All the information a provider needs to publish one video."""
    # Source video
    video_url:          str
    caption:            str
    hashtags:           list[str]           = field(default_factory=list)
    thumbnail_url:      str | None          = None
    # OAuth credential for the target account
    access_token:       str                 = ""
    refresh_token:      str | None          = None
    platform_user_id:   str                 = ""
    # Platform-specific overrides (privacy, duet, stitch, category, etc.)
    options:            dict[str, Any]      = field(default_factory=dict)


@dataclass
class PublishResult:
    """Returned immediately by publish_video() — may still be processing."""
    platform_publish_id:  str
    status:               PublishStatus
    platform_url:         str | None        = None
    error_code:           str | None        = None
    error_message:        str | None        = None
    metadata:             dict[str, Any]    = field(default_factory=dict)


@dataclass
class PublishStatusResult:
    """Returned by get_publish_status() — poll until terminal."""
    platform_publish_id:  str
    status:               PublishStatus
    platform_url:         str | None        = None
    error_code:           str | None        = None
    error_message:        str | None        = None
    metadata:             dict[str, Any]    = field(default_factory=dict)


@dataclass
class OAuthTokenResult:
    """Returned by exchange_code() after the OAuth callback."""
    access_token:       str
    refresh_token:      str | None
    expires_in:         int | None          # seconds; None = non-expiring
    platform_user_id:   str
    platform_username:  str | None          = None
    platform_name:      str | None          = None
    scopes:             list[str]           = field(default_factory=list)
    metadata:           dict[str, Any]      = field(default_factory=dict)


# ── Abstract base ─────────────────────────────────────────────────────────────

class SocialPublisherProvider(ABC):
    """
    Subclass once per platform (TikTok, Instagram, YouTube).

    All methods are async — implementations use httpx for API calls.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def platform_id(self) -> str:
        """Stable slug — 'tiktok', 'instagram', 'youtube'. Never changes."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    def is_available(self) -> bool:
        """Return True if the required env vars / credentials are present.
        Default: always available (useful for mock in dev/test)."""
        return True

    # ── OAuth ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Build the platform OAuth authorization URL.

        The caller stores `state` in Redis (same pattern as Google OAuth)
        and redirects the browser here.
        """
        raise NotImplementedError

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> OAuthTokenResult:
        """Exchange the authorization code for tokens + user info.

        Raises RuntimeError on network/auth failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def refresh_access_token(
        self,
        refresh_token: str,
    ) -> OAuthTokenResult:
        """Refresh an expired access token.

        Raises RuntimeError if the refresh token is invalid/expired.
        """
        raise NotImplementedError

    # ── Publishing ────────────────────────────────────────────────────────────

    @abstractmethod
    async def publish_video(
        self,
        request: PublishRequest,
    ) -> PublishResult:
        """Initiate a video publish.

        Phase 1 (URL-based): instructs the platform to pull the video from
        request.video_url.  Returns immediately with an initial status.
        Terminal statuses (COMPLETED/FAILED) may be returned directly for
        synchronous platforms.

        Raises RuntimeError on unrecoverable API errors — the caller marks
        the social_publish_jobs row as failed.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_publish_status(
        self,
        publish_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        """Poll for the current status of a publish job.

        Called by the job worker until status is COMPLETED or FAILED.
        """
        raise NotImplementedError

    # ── Optional helpers ──────────────────────────────────────────────────────

    async def revoke_token(self, access_token: str) -> None:
        """Best-effort token revocation on disconnect. Default: no-op."""
        return None

    async def get_account_info(
        self,
        access_token: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Fetch live account metadata (follower count, avatar, etc.).

        Default returns an empty dict — override when the platform supports it.
        """
        return {}
