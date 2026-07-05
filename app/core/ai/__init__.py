"""
app.core.ai — AI Platform for Axon AI Automation Studio.

The canonical entry point for all AI functionality.

Quick start::

    from app.core.ai import platform

    resp = await platform.complete(request, user_id=uid)
"""
from .platform import platform, AIPlatform

__all__ = ["platform", "AIPlatform"]
