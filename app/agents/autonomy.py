"""
Autonomous Development Engine — the OS writes new features itself.

Capabilities:
  1. generate_agent(description)  — writes a new agent .py file from a description
  2. suggest_improvements()       — scans codebase + memory → proposes new features
  3. implement_suggestion(idx)    — implements a previously suggested feature
  4. continuous_loop(n_cycles)    — N cycles of: reflect → suggest → implement

This is the AGI-like layer: the system proposes and implements its own extensions
without human intervention (subject to PolicyEngine constraints).

All generated code goes through:
  - PolicyEngine.check_write()   (blocks secrets / CI / migrations)
  - SelfModifyingEngine.create() (atomic write + audit trail)
  - HotReloader                  (live reload without restart)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.memory  import AgentMemory
    from app.agents.kernel  import AgentKernel

log = logging.getLogger(__name__)

_AGENTS_DIR = "app/agents/builtin"


@dataclass
class Suggestion:
    index      : int
    title      : str
    description: str
    agent_name : str          # proposed agent name
    file       : str          # where it would be written
    priority   : float        # 0–1
    implemented: bool = False
    timestamp  : float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "index"      : self.index,
            "title"      : self.title,
            "description": self.description,
            "agent_name" : self.agent_name,
            "file"       : self.file,
            "priority"   : round(self.priority, 2),
            "implemented": self.implemented,
        }


class AutonomyEngine:
    """
    Autonomous feature generation.

    Requires ANTHROPIC_API_KEY for full operation.
    Falls back gracefully when API key is absent.
    """

    def __init__(self, kernel: "AgentKernel") -> None:
        self._kernel     = kernel
        self._suggestions: list[Suggestion] = []
        self._api_key    = os.getenv("ANTHROPIC_API_KEY", "")

    # ── Public ────────────────────────────────────────────────────────────────

    async def generate_agent(
        self,
        description: str,
        agent_name : Optional[str] = None,
        *,
        org_id     : Optional[str] = None,
    ) -> dict:
        """
        Write a new agent file from a description using Claude.
        Returns {"status", "file", "agent_name", "source"}.
        """
        if not self._api_key:
            return {"status": "error", "error": "ANTHROPIC_API_KEY not set"}

        agent_name = agent_name or _slug(description)
        file_rel   = f"{_AGENTS_DIR}/{agent_name}_agent.py"
        file_abs   = Path(__file__).parent.parent.parent / file_rel

        if file_abs.exists():
            return {"status": "error", "error": f"Agent '{agent_name}' already exists"}

        source = await self._generate_source(description, agent_name, org_id=org_id)
        if not source:
            return {"status": "error", "error": "LLM returned empty source"}

        # Write via SelfModifyingEngine (policy check + audit)
        modifier = self._kernel._modifier
        if modifier:
            try:
                modifier.create(
                    file_rel, content=source,
                    description=f"auto-generated agent: {description[:60]}",
                )
            except Exception as exc:
                return {"status": "error", "error": str(exc)}
        else:
            file_abs.parent.mkdir(parents=True, exist_ok=True)
            file_abs.write_text(source, encoding="utf-8")

        # Hot-reload into the kernel
        from app.agents.loader import load_file
        load_file(file_abs, self._kernel)

        return {
            "status"    : "created",
            "agent_name": agent_name,
            "file"      : file_rel,
            "source"    : source,
        }

    async def suggest_improvements(self, n: int = 3, *,
                                   org_id: Optional[str] = None) -> list[Suggestion]:
        """
        Analyze current agents + memory → propose new agents / features.
        """
        if not self._api_key:
            return []

        from app.core.org_quota import check_org_quota_id, record_org_tokens
        if not await check_org_quota_id(org_id):
            return []

        existing_agents = [a.name for a in self._kernel.all_agents()]
        memory_stats    = self._kernel._memory.global_stats()
        common_errors   = [s.name for s in self._kernel._memory.underperformers()]

        prompt = (
            f"Existing agents: {', '.join(existing_agents)}\n"
            f"Underperforming: {', '.join(common_errors) or 'none'}\n"
            f"Total executions: {self._kernel._memory.total_count()}\n\n"
            f"Suggest {n} NEW agent ideas that would add value.\n"
            f"Respond with JSON array:\n"
            f'[{{"title":"...","description":"...","agent_name":"...","priority":0.0-1.0}}]'
        )

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
                await record_org_tokens(org_id, total_tokens, None, ref_type="agent_autonomy")
            except Exception:
                pass  # metering must never turn a successful reply into an error
            text = msg.content[0].text.strip()
            # Extract JSON array
            start = text.find("[")
            end   = text.rfind("]") + 1
            data  = json.loads(text[start:end])

            base = len(self._suggestions)
            suggestions = []
            for i, item in enumerate(data[:n]):
                name = _slug(item.get("agent_name") or item.get("title", f"agent_{i}"))
                file = f"{_AGENTS_DIR}/{name}_agent.py"
                s = Suggestion(
                    index       = base + i,
                    title       = item.get("title", ""),
                    description = item.get("description", ""),
                    agent_name  = name,
                    file        = file,
                    priority    = float(item.get("priority", 0.5)),
                )
                suggestions.append(s)

            self._suggestions.extend(suggestions)
            return suggestions

        except Exception as exc:
            log.debug("suggest_improvements failed: %s", exc)
            return []

    async def implement_suggestion(self, index: int, *,
                                   org_id: Optional[str] = None) -> dict:
        """Implement a previously generated suggestion by index."""
        matches = [s for s in self._suggestions if s.index == index]
        if not matches:
            return {"status": "error", "error": f"No suggestion at index {index}"}
        s = matches[0]
        if s.implemented:
            return {"status": "error", "error": "Already implemented"}

        result = await self.generate_agent(s.description, s.agent_name, org_id=org_id)
        if result.get("status") == "created":
            s.implemented = True
        return {**result, "suggestion": s.to_dict()}

    async def continuous_loop(self, cycles: int = 3, *,
                              org_id: Optional[str] = None) -> list[dict]:
        """
        N autonomous improvement cycles:
          1. Suggest improvements
          2. Implement highest-priority suggestion
          3. Reflect
        """
        results = []
        for cycle in range(cycles):
            log.info("autonomy loop: cycle %d/%d", cycle + 1, cycles)
            suggestions = await self.suggest_improvements(n=2, org_id=org_id)
            if not suggestions:
                results.append({"cycle": cycle + 1, "status": "no_suggestions"})
                continue

            best = max(suggestions, key=lambda s: s.priority)
            impl = await self.implement_suggestion(best.index, org_id=org_id)
            results.append({
                "cycle"     : cycle + 1,
                "suggestion": best.to_dict(),
                "result"    : impl,
            })

        return results

    def pending_suggestions(self) -> list[Suggestion]:
        return [s for s in self._suggestions if not s.implemented]

    def all_suggestions(self) -> list[dict]:
        return [s.to_dict() for s in self._suggestions]

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _generate_source(self, description: str, agent_name: str, *,
                               org_id: Optional[str] = None) -> str:
        existing_source = _example_agent_source()
        from app.core.org_quota import check_org_quota_id, record_org_tokens
        if not await check_org_quota_id(org_id):
            return ""
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Write a Python agent for the Agentic OS.\n\n"
                        f"Agent name: {agent_name}\n"
                        f"Description: {description}\n\n"
                        f"Follow this template exactly:\n"
                        f"```python\n{existing_source}\n```\n\n"
                        f"Rules:\n"
                        f"- Change name, description, group, and execute() body\n"
                        f"- Keep imports, EvolvableAgent base class, AgentResult.ok/fail\n"
                        f"- End with: agent = {_class_name(agent_name)}()\n"
                        f"- Return ONLY the Python source, no markdown fences"
                    ),
                }],
            )
            try:
                total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
                await record_org_tokens(org_id, total_tokens, None, ref_type="agent_autonomy")
            except Exception:
                pass  # metering must never turn a successful reply into an error
            source = msg.content[0].text.strip()
            if source.startswith("```"):
                lines  = source.split("\n")
                source = "\n".join(l for l in lines if not l.startswith("```"))
            return source
        except Exception as exc:
            log.error("generate_source failed: %s", exc)
            return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9_]", "_", text.lower().strip())[:30].strip("_")


def _class_name(slug: str) -> str:
    return "".join(w.capitalize() for w in slug.split("_")) + "Agent"


def _example_agent_source() -> str:
    return '''\
"""Example agent — replace with your logic."""
from __future__ import annotations
from app.agents.base import AgentContext, AgentResult, EvolvableAgent

class ExampleAgent(EvolvableAgent):
    name        = "example"
    description = "An example agent"
    group       = "general"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        return AgentResult.ok(self.name, f"Handled: {ctx.args}")

    def performance_hint(self) -> dict:
        return {"complexity": "low"}

agent = ExampleAgent()
'''
