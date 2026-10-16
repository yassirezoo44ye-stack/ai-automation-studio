"""
SocialPublisherRegistry — resolves the active provider for a platform slug.

Resolution: built-in catalogue keyed by platform_id.  Platform clients are
registered here; the router never imports platform modules directly.

Adding a new platform:
    1. Subclass SocialPublisherProvider in its own module (e.g. tiktok.py)
    2. Import and add to _PROVIDERS below
    3. Done
"""
from __future__ import annotations

from typing import Optional

from app.integrations.social.base import SocialPublisherProvider
from app.integrations.social.mock import MockSocialPublisherProvider
from app.integrations.social.instagram import InstagramProvider
from app.integrations.social.tiktok import TikTokProvider

# ── Built-in provider catalogue ───────────────────────────────────────────────
# Replace mock entries with real providers as each platform is implemented.
_PROVIDERS: dict[str, SocialPublisherProvider] = {
    "mock":      MockSocialPublisherProvider("mock",      "Mock Platform"),
    "tiktok":    TikTokProvider(),           # Step 2 — requires TIKTOK_CLIENT_KEY/SECRET
    "instagram": InstagramProvider(),        # Step 3 — requires INSTAGRAM_APP_ID/APP_SECRET
    # "youtube":   YouTubeProvider(),        # Step 4
}


class SocialPublisherRegistry:

    def get(self, platform_id: str) -> Optional[SocialPublisherProvider]:
        """Return the provider for platform_id, or None if not registered."""
        return _PROVIDERS.get(platform_id)

    def get_or_raise(self, platform_id: str) -> SocialPublisherProvider:
        """Return the provider or raise ValueError (caller maps to 400/422)."""
        provider = _PROVIDERS.get(platform_id)
        if provider is None:
            raise ValueError(f"Unknown platform: {platform_id!r}")
        return provider

    def list_platforms(self) -> list[dict]:
        """Metadata for all registered platforms (UI integration catalog)."""
        return [
            {
                "platform_id":   p.platform_id,
                "display_name":  p.display_name,
                "available":     p.is_available(),
            }
            for p in _PROVIDERS.values()
            if p.platform_id != "mock"
        ]


_registry = SocialPublisherRegistry()


def get_social_registry() -> SocialPublisherRegistry:
    return _registry
