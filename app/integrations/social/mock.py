"""
MockSocialPublisherProvider — deterministic fake for tests and local dev.

Behaviour:
• get_auth_url()      → returns a local /mock-oauth URL (no external call)
• exchange_code()     → accepts any code; returns a fake token
• publish_video()     → always succeeds immediately; platform_publish_id = 'mock-{uuid}'
• get_publish_status() → always returns COMPLETED
• refresh_access_token() → extends expiry by 3600 s
"""
from __future__ import annotations

import uuid
from typing import Any

from app.integrations.social.base import (
    OAuthTokenResult,
    PublishRequest,
    PublishResult,
    PublishStatus,
    PublishStatusResult,
    SocialPublisherProvider,
)


class MockSocialPublisherProvider(SocialPublisherProvider):

    def __init__(self, platform: str = "mock", name: str = "Mock Platform") -> None:
        self._platform = platform
        self._name = name

    @property
    def platform_id(self) -> str:
        return self._platform

    @property
    def display_name(self) -> str:
        return self._name

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        return f"/api/social/mock-oauth-callback?state={state}&code=mock-code"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        return OAuthTokenResult(
            access_token=f"mock-access-{uuid.uuid4().hex[:8]}",
            refresh_token=f"mock-refresh-{uuid.uuid4().hex[:8]}",
            expires_in=3600,
            platform_user_id=f"mock-user-{uuid.uuid4().hex[:8]}",
            platform_username="mock_creator",
            platform_name="Mock Creator",
            scopes=["video.upload", "user.info.basic"],
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        return OAuthTokenResult(
            access_token=f"mock-access-{uuid.uuid4().hex[:8]}",
            refresh_token=refresh_token,
            expires_in=3600,
            platform_user_id="mock-user-refreshed",
            scopes=["video.upload", "user.info.basic"],
        )

    async def publish_video(self, request: PublishRequest) -> PublishResult:
        return PublishResult(
            platform_publish_id=f"mock-{uuid.uuid4().hex[:12]}",
            status=PublishStatus.COMPLETED,
            platform_url=f"https://mock.example.com/video/{uuid.uuid4().hex[:8]}",
        )

    async def get_publish_status(
        self,
        publish_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        return PublishStatusResult(
            platform_publish_id=publish_id,
            status=PublishStatus.COMPLETED,
            platform_url=f"https://mock.example.com/video/{publish_id}",
        )

    async def get_account_info(
        self,
        access_token: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        return {
            "platform_user_id": platform_user_id,
            "username": "mock_creator",
            "follower_count": 42,
        }
