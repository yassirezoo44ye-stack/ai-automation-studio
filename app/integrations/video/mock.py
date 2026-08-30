"""
MockVideoProvider — deterministic in-process provider for development and tests.

Never calls any external API. Returns a fixed "completed" response so the
entire Training Studio pipeline can be exercised end-to-end without
Synthesia/HeyGen credentials.

Usage: registered automatically in registry.py; the router resolves it
when no org-specific provider is configured.
"""
from __future__ import annotations

import secrets
from typing import Any

from app.integrations.video.base import (
    VideoCreateResult, VideoProvider, VideoStatus, VideoStatusResult,
)


_MOCK_THUMBNAIL = (
    "https://placehold.co/1280x720/6e32e0/ffffff?text=Training+Video"
)
_MOCK_VIDEO_URL = (
    "https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"
)


class MockVideoProvider(VideoProvider):
    """
    Fake provider that immediately returns a completed video.
    Suitable for Phase 1 development and CI tests.
    """

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def display_name(self) -> str:
        return "Mock (Development)"

    def is_available(self, config: dict[str, Any]) -> bool:
        # Mock is always available — no credentials required.
        return True

    async def create_video(
        self,
        *,
        title:     str,
        script:    str,
        language:  str                  = "en",
        avatar_id: str | None           = None,
        voice_id:  str | None           = None,
        config:    dict[str, Any] | None = None,
    ) -> VideoCreateResult:
        # Generate a stable-looking fake provider video ID.
        fake_id = f"mock_{secrets.token_hex(8)}"
        return VideoCreateResult(
            provider_video_id=fake_id,
            status=VideoStatus.COMPLETED,
            url=_MOCK_VIDEO_URL,
            thumbnail_url=_MOCK_THUMBNAIL,
            duration_seconds=len(script.split()) // 3,  # rough words-per-second estimate
            metadata={
                "mock": True,
                "title": title,
                "language": language,
                "avatar_id": avatar_id,
                "voice_id": voice_id,
                "script_length": len(script),
            },
        )

    async def get_video_status(
        self,
        video_id: str,
        config:   dict[str, Any] | None = None,
    ) -> VideoStatusResult:
        return VideoStatusResult(
            provider_video_id=video_id,
            status=VideoStatus.COMPLETED,
            url=_MOCK_VIDEO_URL,
            thumbnail_url=_MOCK_THUMBNAIL,
        )
