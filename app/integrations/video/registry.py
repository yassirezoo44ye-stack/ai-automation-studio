"""
VideoProviderRegistry — resolves the active VideoProvider for a request.

Resolution order (first match wins):
    1. org-configured provider  (training_providers DB row with enabled=True)
    2. env-configured default   (VIDEO_PROVIDER env var)
    3. MockVideoProvider        (always available; safe fallback for dev)

Adding a new provider:
    1. Subclass VideoProvider in its own module (e.g. synthesia.py)
    2. Import and add to _BUILTIN_PROVIDERS below
    3. Done — the registry resolves it by provider_id string
"""
from __future__ import annotations

import os
from typing import Optional

from app.integrations.video.base import VideoProvider
from app.integrations.video.mock import MockVideoProvider

# ── Built-in provider catalogue ───────────────────────────────────────────────
# Add new providers here; the registry never imports from the router.
_BUILTIN_PROVIDERS: dict[str, VideoProvider] = {
    "mock": MockVideoProvider(),
    # "synthesia": SynthesiaProvider(),   # Phase 3
    # "heygen":    HeyGenProvider(),      # Phase 3+
}

_DEFAULT_PROVIDER_ID = os.getenv("VIDEO_PROVIDER", "mock")


class VideoProviderRegistry:
    """Thin resolver — no state beyond the built-in catalogue."""

    def get(self, provider_id: str) -> Optional[VideoProvider]:
        """Return the provider for the given ID, or None if unknown."""
        return _BUILTIN_PROVIDERS.get(provider_id)

    def get_default(self) -> VideoProvider:
        """Return the env-configured default provider, falling back to mock."""
        return _BUILTIN_PROVIDERS.get(_DEFAULT_PROVIDER_ID, _BUILTIN_PROVIDERS["mock"])

    def list_available(self) -> list[dict]:
        """Return metadata for all registered providers (used by /api/training/providers)."""
        return [
            {"provider_id": pid, "display_name": p.display_name}
            for pid, p in _BUILTIN_PROVIDERS.items()
        ]


# Module-level singleton — import this everywhere.
_registry = VideoProviderRegistry()


def get_video_registry() -> VideoProviderRegistry:
    return _registry
