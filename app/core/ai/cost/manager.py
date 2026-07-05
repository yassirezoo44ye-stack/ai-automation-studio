"""
CostManager — tracks and enforces spending across all scopes.

Scopes: request | conversation | project | workspace | global (per user).
Records every cost event; checks budget limits before execution.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from ..events.bus    import EventBus
from ..events.events import CostRecorded, BudgetExceeded

if TYPE_CHECKING:
    import asyncpg


@dataclass
class CostRecord:
    amount_usd:      float
    provider_id:     str
    model:           str
    user_id:         Optional[str]  = None
    conversation_id: Optional[str]  = None
    project_id:      Optional[str]  = None
    agent_name:      Optional[str]  = None
    timestamp:       float          = field(default_factory=time.time)


@dataclass
class SpendingLimit:
    scope:     str    # "request"|"conversation"|"project"|"global"
    scope_id:  str    # user_id or project_id etc.
    limit_usd: float


class BudgetError(Exception):
    """Raised when a spending limit would be exceeded."""
    def __init__(self, scope: str, limit: float, actual: float) -> None:
        super().__init__(f"Budget exceeded for {scope}: ${actual:.4f} > ${limit:.4f}")
        self.scope = scope
        self.limit = limit
        self.actual = actual


class CostManager:
    """
    Records all AI costs and enforces spending limits.

    Stores records in-memory (for dashboards) and optionally persists to DB.
    """

    def __init__(
        self,
        bus:          EventBus,
        pool:         Optional["asyncpg.Pool"] = None,
        global_limit: Optional[float]          = None,
    ) -> None:
        self._bus      = bus
        self._pool     = pool
        self._records: list[CostRecord] = []
        self._limits:  list[SpendingLimit] = []
        if global_limit is not None:
            self._limits.append(SpendingLimit("global", "*", global_limit))

    def init(self, pool: "asyncpg.Pool") -> None:
        self._pool = pool

    def add_limit(self, limit: SpendingLimit) -> None:
        self._limits.append(limit)

    async def check_budget(
        self,
        user_id:        Optional[str],
        project_id:     Optional[str],
        estimated_cost: float,
        limit_usd:      float,
    ) -> None:
        """Raise BudgetError if estimated_cost would exceed limit_usd."""
        current = self.total_for_user(user_id)
        if current + estimated_cost > limit_usd:
            await self._bus.emit(BudgetExceeded(
                scope="request",
                scope_id=user_id or "",
                limit_usd=limit_usd,
                actual_usd=current + estimated_cost,
            ))
            raise BudgetError("request", limit_usd, current + estimated_cost)

    async def record(
        self,
        user_id:         Optional[str],
        project_id:      Optional[str],
        conversation_id: Optional[str],
        amount_usd:      float,
        provider_id:     str,
        model:           str,
        agent_name:      Optional[str] = None,
    ) -> None:
        record = CostRecord(
            amount_usd=amount_usd,
            provider_id=provider_id,
            model=model,
            user_id=user_id,
            conversation_id=conversation_id,
            project_id=project_id,
            agent_name=agent_name,
        )
        self._records.append(record)

        await self._bus.emit(CostRecorded(
            amount_usd=amount_usd,
            provider_id=provider_id,
            model=model,
            conversation_id=conversation_id,
            project_id=project_id,
            agent_name=agent_name,
        ))

        # Check limits
        for limit in self._limits:
            actual = self._scope_total(limit)
            if actual > limit.limit_usd:
                await self._bus.emit(BudgetExceeded(
                    scope=limit.scope,
                    scope_id=limit.scope_id,
                    limit_usd=limit.limit_usd,
                    actual_usd=actual,
                ))

        # Persist to DB
        if self._pool:
            await self._persist(record)

    def total_for_user(self, user_id: Optional[str]) -> float:
        if user_id is None:
            return 0.0
        return sum(r.amount_usd for r in self._records if r.user_id == user_id)

    def total_for_project(self, project_id: str) -> float:
        return sum(r.amount_usd for r in self._records if r.project_id == project_id)

    def by_provider(self, user_id: Optional[str] = None) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self._records:
            if user_id and r.user_id != user_id:
                continue
            out[r.provider_id] = out.get(r.provider_id, 0.0) + r.amount_usd
        return out

    def by_agent(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self._records:
            key = r.agent_name or "direct"
            out[key] = out.get(key, 0.0) + r.amount_usd
        return out

    def summary(self) -> dict[str, Any]:
        total = sum(r.amount_usd for r in self._records)
        return {
            "total_usd":     round(total, 6),
            "record_count":  len(self._records),
            "by_provider":   self.by_provider(),
            "by_agent":      self.by_agent(),
            "limits":        [{"scope": l.scope, "limit_usd": l.limit_usd} for l in self._limits],
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _scope_total(self, limit: SpendingLimit) -> float:
        if limit.scope == "global":
            return sum(r.amount_usd for r in self._records)
        if limit.scope == "project":
            return self.total_for_project(limit.scope_id)
        if limit.scope == "conversation":
            return sum(r.amount_usd for r in self._records if r.conversation_id == limit.scope_id)
        return 0.0

    async def _persist(self, record: CostRecord) -> None:
        try:
            await self._pool.execute(   # type: ignore[union-attr]
                """
                INSERT INTO ai_usage
                  (user_id, provider_id, model, input_tokens, output_tokens,
                   cost_usd, conversation_id, created_at)
                VALUES ($1, $2, $3, 0, 0, $4, $5, NOW())
                ON CONFLICT DO NOTHING
                """,
                record.user_id,
                record.provider_id,
                record.model,
                record.amount_usd,
                record.conversation_id,
            )
        except Exception:
            pass   # DB errors don't block the request
