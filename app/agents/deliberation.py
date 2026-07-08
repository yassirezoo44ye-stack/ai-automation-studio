"""
Multi-Agent Deliberation — agents discuss and vote before execution.

When a task is complex or ambiguous (confidence < 0.8), the kernel can
invoke deliberation:

  1. Candidate agents submit their "bid" for the task
  2. Each agent scores the task on: relevance, confidence, cost, risk
  3. Scores are aggregated with weighted voting
  4. Winner executes; runner-ups are logged as alternatives
  5. (Optional) LLM moderator resolves ties

This produces a richer decision trail and prevents a single wrong agent
from handling something it shouldn't.

Usage:
    deliberation = Deliberation(known_agents)
    winner, votes = await deliberation.vote("deploy to production", kernel)
    result = await winner.run(ctx)
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base   import EvolvableAgent, AgentContext
    from app.agents.kernel import AgentKernel

log = logging.getLogger(__name__)


@dataclass
class AgentBid:
    agent_name  : str
    relevance   : float   # 0–1: how relevant is this agent to the task?
    confidence  : float   # 0–1: how confident is the agent it can handle it?
    cost        : float   # 0–1: expected resource cost (1 = highest)
    risk        : float   # 0–1: risk of failure (1 = highest)
    reasoning   : str     = ""

    @property
    def score(self) -> float:
        """Weighted composite score (higher = better candidate)."""
        return (
            self.relevance  * 0.40 +
            self.confidence * 0.35 +
            (1 - self.cost) * 0.15 +
            (1 - self.risk) * 0.10
        )

    def to_dict(self) -> dict:
        return {
            "agent"     : self.agent_name,
            "score"     : round(self.score, 3),
            "relevance" : round(self.relevance, 2),
            "confidence": round(self.confidence, 2),
            "cost"      : round(self.cost, 2),
            "risk"      : round(self.risk, 2),
            "reasoning" : self.reasoning,
        }


@dataclass
class DeliberationResult:
    winner      : str
    winner_score: float
    all_bids    : list[AgentBid] = field(default_factory=list)
    consensus   : float = 0.0    # 0–1: how unanimous was the vote?
    method      : str   = "vote" # vote | llm_tiebreak | single
    reasoning   : str   = ""

    def to_dict(self) -> dict:
        return {
            "winner"      : self.winner,
            "winner_score": round(self.winner_score, 3),
            "consensus"   : round(self.consensus, 2),
            "method"      : self.method,
            "bids"        : [b.to_dict() for b in self.all_bids],
            "reasoning"   : self.reasoning,
        }


# ── Static bid tables ────────────────────────────────────────────────────────
# Keyword → (relevance boost per agent)
# These are prior biases; confidence is still per-task.

_AGENT_BIASES: dict[str, dict[str, float]] = {
    "run"    : {"run": 0.90, "build": 0.30, "deploy": 0.20},
    "build"  : {"build": 0.90, "run": 0.20, "analyze": 0.30},
    "deploy" : {"deploy": 0.90, "build": 0.40, "analyze": 0.20},
    "analyze": {"analyze": 0.90, "status": 0.40},
    "evolve" : {"evolve": 0.90, "analyze": 0.50},
    "plan"   : {"plan": 0.90, "analyze": 0.30},
    "modify" : {"modify": 0.90, "evolve": 0.30},
    "status" : {"status": 0.90, "analyze": 0.40},
    "help"   : {"help": 0.90},
}


class Deliberation:
    """
    Multi-agent voting system.

    Each registered agent casts a bid.  If the top two scores are within 0.05
    of each other, an LLM tiebreak is attempted.
    """

    def __init__(self, min_agents: int = 2) -> None:
        self._min_agents = min_agents

    async def vote(
        self,
        raw_input     : str,
        kernel        : "AgentKernel",
        heuristic_intent: str = "",
    ) -> DeliberationResult:
        """
        Run deliberation and return the winner agent name + full vote record.
        """
        agents = kernel.all_agents()
        if len(agents) == 0:
            return DeliberationResult(winner="help", winner_score=0.0,
                                      method="single", reasoning="No agents registered")
        if len(agents) == 1:
            agent = agents[0]
            return DeliberationResult(winner=agent.name, winner_score=1.0,
                                      method="single", reasoning="Only one agent available")

        # Collect bids (parallel)
        bids = await asyncio.gather(*[
            self._solicit_bid(agent, raw_input, heuristic_intent)
            for agent in agents
        ])
        bids = sorted(bids, key=lambda b: b.score, reverse=True)

        top, second = bids[0], bids[1] if len(bids) > 1 else bids[0]
        gap = top.score - second.score

        if gap < 0.05 and os.getenv("ANTHROPIC_API_KEY"):
            # Tiebreak via LLM
            winner_name, reasoning = await self._llm_tiebreak(
                raw_input, top, second, kernel
            )
            return DeliberationResult(
                winner       = winner_name,
                winner_score = top.score,
                all_bids     = bids,
                consensus    = gap,
                method       = "llm_tiebreak",
                reasoning    = reasoning,
            )

        consensus = 1.0 - (second.score / top.score if top.score > 0 else 0)
        return DeliberationResult(
            winner       = top.agent_name,
            winner_score = top.score,
            all_bids     = bids,
            consensus    = consensus,
            method       = "vote",
            reasoning    = top.reasoning,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _solicit_bid(
        self,
        agent           : "EvolvableAgent",
        raw_input       : str,
        heuristic_intent: str,
    ) -> AgentBid:
        """Generate a bid for the agent based on keyword biases + hints."""
        biases     = _AGENT_BIASES.get(agent.name, {})
        hints      = agent.performance_hint()
        base_rel   = biases.get(agent.name, 0.3)
        intent_boost = 0.5 if heuristic_intent == agent.name else 0.0
        relevance  = min(1.0, base_rel + intent_boost)

        # Cost / risk from hints
        complexity = hints.get("complexity", "medium")
        cost  = {"low": 0.1, "medium": 0.4, "high": 0.8}.get(complexity, 0.4)
        risk  = 0.6 if hints.get("writes_files") else 0.2
        risk  = 0.8 if hints.get("llm_needed") and not os.getenv("ANTHROPIC_API_KEY") else risk

        return AgentBid(
            agent_name = agent.name,
            relevance  = relevance,
            confidence = min(1.0, relevance + 0.1),
            cost       = cost,
            risk       = risk,
            reasoning  = f"{agent.name}: relevance={relevance:.2f} cost={cost:.2f}",
        )

    async def _llm_tiebreak(
        self,
        raw_input: str,
        top      : AgentBid,
        second   : AgentBid,
        kernel   : "AgentKernel",
    ) -> tuple[str, str]:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Task: {raw_input}\n"
                        f"Agent A: {top.agent_name} (score {top.score:.2f})\n"
                        f"Agent B: {second.agent_name} (score {second.score:.2f})\n"
                        f"Reply with exactly: WINNER: <agent_name> | REASON: <one sentence>"
                    ),
                }],
            )
            text = msg.content[0].text.strip()
            if "WINNER:" in text:
                parts  = text.split("|")
                winner = parts[0].replace("WINNER:", "").strip().lower()
                reason = parts[1].replace("REASON:", "").strip() if len(parts) > 1 else ""
                if winner in (top.agent_name, second.agent_name):
                    return winner, reason
        except Exception as exc:
            log.debug("llm tiebreak failed: %s", exc)
        return top.agent_name, "defaulting to highest score"
