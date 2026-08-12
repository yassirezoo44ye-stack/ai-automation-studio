"""A deterministic, network-free AIProvider — selected via `AI_PROVIDER=mock`.

This exists for local development without an API key, CI, and end-to-end
tests (Step 12 of the Phase 2 spec: CI must not depend on real AI
credentials). It is NOT a "fake production feature": it's clearly named,
returns obviously-canned content, and app/services/ai/factory.py never
selects it by default — a real deployment must explicitly opt in to it,
which `Settings.validate_for_production()` refuses to allow (see factory.py).
"""
from __future__ import annotations

from typing import Any

from app.services.ai.provider import AIProvider


class MockAIProvider(AIProvider):
    @property
    def model_name(self) -> str:
        return "mock-provider-v1"

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return "This is a deterministic mock response for local development/testing."

    async def generate_structured(
        self, *, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 2048,
    ) -> dict[str, Any]:
        if "ideas" in schema.get("properties", {}):
            return {
                "ideas": [
                    {
                        "title": "5 AI tools your team isn't using yet",
                        "hook": "Most teams only scratch the surface of what AI can do.",
                        "concept": "A roundup of underrated AI tools that save hours every week.",
                        "pillar": "AI Tools",
                        "suggested_platform": "linkedin",
                        "cta": "Which one will you try first?",
                    },
                    {
                        "title": "Myth vs fact: AI hallucinations",
                        "hook": "AI doesn't lie — it guesses when it isn't sure.",
                        "concept": "A myth-vs-fact breakdown of why AI sometimes makes things up.",
                        "pillar": "AI Education",
                        "suggested_platform": "x",
                        "cta": "Follow for more AI myths, debunked.",
                    },
                ],
            }
        return {
            "hook": "Most teams only scratch the surface of what AI can do.",
            "body": "Here are 5 AI tools that will change how your team works this week.",
            "cta": "Try one today and tell us what you think.",
            "hashtags": ["ai", "productivity", "tools"],
            "platform": "linkedin",
            "media_concept": "A simple carousel graphic listing the 5 tools with one-line descriptions.",
        }
