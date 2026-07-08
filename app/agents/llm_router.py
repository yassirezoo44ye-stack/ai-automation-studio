"""
LLM Router — Claude-backed intent understanding.

Replaces the heuristic IntentParser for inputs where confidence < 0.6.
Returns a structured IntentResult with agent, args, confidence, reasoning.

The router uses a lightweight model (Haiku) with a structured prompt so that
intent classification is fast (<300ms) and cheap.  Falls back gracefully to
the heuristic parser when the API key is missing or the call fails.

Used by AgentKernel.run() automatically.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the intent router for an Agentic OS.
Given user input, identify the best agent to handle it.

Respond with ONLY a JSON object on one line:
{"intent":"<name>","args":"<remaining args>","confidence":0.0-1.0,"reason":"<one line>"}

Rules:
- intent must be one of the available agents listed below
- args is the input with the intent verb stripped out
- confidence: 1.0 = certain, 0.5 = unsure
- reason: one short sentence
"""


@dataclass
class RoutedIntent:
    intent    : str
    args      : str
    confidence: float
    reason    : str
    method    : str = "llm"
    raw_input : str = ""
    suggestions: list[str] = field(default_factory=list)


class LLMRouter:
    """
    Claude-backed intent router.

    Usage:
        router = LLMRouter()
        result = await router.route("fix the slow build pipeline", known_agents)
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")

    def available(self) -> bool:
        return bool(self._api_key)

    async def route(self, raw_input: str, known_agents: list[str]) -> Optional[RoutedIntent]:
        """
        Route raw_input to an agent via Claude.
        Returns None if unavailable or if the call fails.
        """
        if not self._api_key:
            return None

        agent_list = ", ".join(known_agents)
        user_msg   = f"Available agents: {agent_list}\nUser input: {raw_input}"

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=128,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = msg.content[0].text.strip()

            # Extract JSON even if wrapped in markdown fences
            match = re.search(r'\{[^}]+\}', text)
            if not match:
                return None

            data   = json.loads(match.group())
            intent = data.get("intent", "").lower().strip()

            if intent not in known_agents:
                log.debug("llm router returned unknown agent %r", intent)
                return None

            return RoutedIntent(
                intent     = intent,
                args       = str(data.get("args", "")),
                confidence = float(data.get("confidence", 0.7)),
                reason     = str(data.get("reason", "")),
                method     = "llm",
                raw_input  = raw_input,
            )

        except Exception as exc:
            log.debug("llm router failed: %s", exc)
            return None

    async def understand(self, raw_input: str, known_agents: list[str],
                         context: str = "") -> RoutedIntent:
        """
        Full understanding: route + validate.
        Always returns a RoutedIntent (never raises).
        """
        result = await self.route(raw_input, known_agents)
        if result:
            return result

        # Fallback — mark as unknown
        return RoutedIntent(
            intent     = "unknown",
            args       = raw_input,
            confidence = 0.0,
            reason     = "LLM router unavailable or failed",
            method     = "fallback",
            raw_input  = raw_input,
            suggestions= known_agents[:6],
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
