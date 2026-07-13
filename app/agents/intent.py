"""
IntentParser — converts free-form natural language into (intent, args, confidence).

Pipeline:
  1. Alias / keyword lookup   (exact match, zero latency)
  2. Prefix / contains scan   (fast heuristic)
  3. Levenshtein fuzzy match  (typo tolerance)
  4. LLM fallback             (complex sentences — only when above fail)

Returns:
  IntentResult(intent, args, confidence, method)
"""
from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ── Intent aliases ─────────────────────────────────────────────────────────────
# Maps natural-language phrases → canonical agent name
_ALIASES: dict[str, str] = {
    # run
    "run":     "run",  "execute": "run",  "start":  "run",  "launch": "run",
    "serve":   "run",

    # build
    "build":   "build", "compile": "build", "bundle": "build", "package": "build",
    "dist":    "build",

    # deploy
    "deploy":  "deploy", "release": "deploy", "publish": "deploy", "ship": "deploy",
    "push":    "deploy",

    # analyze
    "analyze": "analyze", "analyse": "analyze", "inspect": "analyze",
    "profile": "analyze", "audit":   "analyze", "check":   "analyze",
    "review":  "analyze",

    # modify / patch
    "modify":  "modify", "patch":   "modify", "edit":    "modify",
    "fix":     "modify", "rewrite": "modify", "update":  "modify",

    # evolve
    "evolve":  "evolve", "optimize": "evolve", "improve": "evolve",
    "upgrade": "evolve", "tune":     "evolve",

    # plan
    "plan":    "plan",   "decompose": "plan", "schedule": "plan",
    "outline": "plan",   "strategy":  "plan",

    # status / help
    "status":  "status", "info":    "status", "stats":   "status",
    "health":  "status",
    "help":    "help",   "?":       "help",   "h":       "help",

    # agents
    "agents":  "agents", "list":    "agents",
}

# Patterns for intent extraction from sentences
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(run|execute|start|launch|serve)\b",   re.I), "run"),
    (re.compile(r"\b(build|compile|bundle|package)\b",     re.I), "build"),
    (re.compile(r"\b(deploy|release|publish|ship)\b",      re.I), "deploy"),
    (re.compile(r"\b(analyz|audit|inspect|profile|check)\b", re.I), "analyze"),
    (re.compile(r"\b(modify|patch|fix|rewrite|edit)\b",    re.I), "modify"),
    (re.compile(r"\b(evolv|optim|improv|upgrad|tune)\b",   re.I), "evolve"),
    (re.compile(r"\b(plan|decompose|strateg)\b",            re.I), "plan"),
    (re.compile(r"\b(status|health|stats|info)\b",          re.I), "status"),
]


@dataclass
class IntentResult:
    intent    : str
    args      : str
    confidence: float           # 0.0–1.0
    method    : str             # "alias" | "prefix" | "pattern" | "fuzzy" | "llm" | "unknown"
    raw       : str = ""
    suggestions: list[str] = field(default_factory=list)


class IntentParser:
    """
    Stateless intent parser.  Registered agent names are used for fuzzy matching.
    """

    def __init__(self, known_agents: list[str] | None = None) -> None:
        self._known: list[str] = known_agents or []

    def update_agents(self, names: list[str]) -> None:
        self._known = names

    # ── Public ────────────────────────────────────────────────────────────────

    def parse(self, raw: str) -> IntentResult:
        text = raw.strip()
        if not text:
            return IntentResult("help", "", 1.0, "alias", raw)

        # Try shlex split first for command-style input
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()

        first = parts[0].lower() if parts else ""
        rest  = " ".join(parts[1:])

        # 1. Exact alias
        if first in _ALIASES:
            return IntentResult(_ALIASES[first], rest, 1.0, "alias", raw)

        # 2. Prefix match against known agents
        for name in self._known:
            if first == name:
                return IntentResult(name, rest, 1.0, "prefix", raw)

        # 3. Pattern scan (natural language sentences)
        for pattern, intent in _PATTERNS:
            if pattern.search(text):
                # args = everything except the matched verb
                args = pattern.sub("", text).strip()
                return IntentResult(intent, args or rest, 0.85, "pattern", raw)

        # 4. Fuzzy match against known agents + alias keys
        all_names = list(set(list(_ALIASES.keys()) + self._known))
        best, dist = _closest(first, all_names)
        if dist <= 2:
            resolved = _ALIASES.get(best, best)
            return IntentResult(resolved, rest, max(0.4, 1.0 - dist * 0.3), "fuzzy", raw,
                                suggestions=[resolved])

        # 5. Unknown — return with suggestions
        return IntentResult(
            "unknown", text, 0.0, "unknown", raw,
            suggestions=sorted(set(_ALIASES.values()))[:8],
        )

    async def parse_with_llm(self, raw: str, known_agents: list[str], *,
                             org_id: Optional[str] = None) -> IntentResult:
        """LLM fallback — only called when confidence < 0.5."""
        from app.core.org_quota import check_org_quota_id, record_org_tokens
        if not await check_org_quota_id(org_id):
            return IntentResult("unknown", raw, 0.0, "unknown", raw,
                                suggestions=known_agents[:8])
        try:
            import anthropic
            import os
            client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            agent_list = ", ".join(known_agents)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Available agents: {agent_list}\n"
                        f"User input: {raw!r}\n"
                        f"Reply with exactly: AGENT_NAME | remaining args\n"
                        f"AGENT_NAME must be one of the available agents."
                    ),
                }],
            )
            try:
                total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
                await record_org_tokens(org_id, total_tokens, None, ref_type="agent_intent")
            except Exception:
                pass  # metering must never turn a successful reply into an error
            text = msg.content[0].text.strip()
            if "|" in text:
                intent, args = text.split("|", 1)
                intent = intent.strip().lower()
                args   = args.strip()
                if intent in known_agents:
                    return IntentResult(intent, args, 0.8, "llm", raw)
        except Exception as exc:
            log.debug("llm intent fallback failed: %s", exc)

        return IntentResult("unknown", raw, 0.0, "unknown", raw,
                            suggestions=known_agents[:8])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                            prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def _closest(word: str, candidates: list[str]) -> tuple[str, int]:
    if not candidates:
        return ("", 999)
    scored = [(c, _levenshtein(word, c)) for c in candidates]
    return min(scored, key=lambda x: x[1])
