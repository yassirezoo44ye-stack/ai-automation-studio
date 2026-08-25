"""
Video provider package.

Follows the same pattern as app/integrations/provider.py:
stateless business logic behind an ABC, with a registry that the
Training Studio router resolves at request time.
"""
from app.integrations.video.base import VideoProvider, VideoStatus
from app.integrations.video.registry import VideoProviderRegistry, get_video_registry

__all__ = ["VideoProvider", "VideoStatus", "VideoProviderRegistry", "get_video_registry"]
