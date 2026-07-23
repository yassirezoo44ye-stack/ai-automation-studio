"""
Agent Memory Layer — persistent execution history with per-agent performance tracking.

Stores every execution record:
  - agent name, input, result, duration, success/failure
  - persisted atomically to $TMPDIR/agent-memory.json

Provides:
  - add(record)        — append a new execution
  - recent(n)          — last n records
  - for_agent(name)    — all records for a specific agent
  - stats(name)        — success_rate, avg_ms, call_count for one agent
  - global_stats()     — stats for all agents, sorted by call_count
  - underperformers(threshold) — agents with success_rate below threshold
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Sentinel distinguishing "org_id not specified at all" (unscoped,
# cross-tenant — internal use only) from "org_id explicitly passed as
# None" (the no-org bucket — a real, filterable value, not "everything").
_UNSCOPED = object()

_MEMORY_FILE = Path(tempfile.gettempdir()) / "agent-memory.json"
_MAX_RECORDS  = 10_000          # rolling window — older records evicted


@dataclass
class ExecutionRecord:
    agent      : str
    input      : str
    args       : str
    success    : bool
    duration_ms: float
    timestamp  : float = field(default_factory=time.time)
    error      : Optional[str] = None
    data       : dict  = field(default_factory=dict)
    organization_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentStats:
    name        : str
    call_count  : int
    success_count: int
    fail_count  : int
    avg_ms      : float
    success_rate: float     # 0.0–1.0
    last_called : Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


class AgentMemory:
    """Thread-safe, persistent rolling execution log."""

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._records : list[ExecutionRecord] = []
        self._load()

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, record: ExecutionRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > _MAX_RECORDS:
                self._records = self._records[-_MAX_RECORDS:]
        self._persist()

    # ── Read ──────────────────────────────────────────────────────────────────

    def recent(self, n: int = 50, *, org_id: Any = _UNSCOPED) -> list[ExecutionRecord]:
        """Most recent `n` records. `org_id` scopes the result to one
        organization's own executions — this is a single, process-wide
        log shared by every tenant, and a record's `input`/`args`/`error`
        may contain confidential business content, so any caller that
        exposes raw record content (not just aggregate stats) to an end
        user MUST pass the calling org's verified id here — including
        explicitly passing `org_id=None` for a caller with no verified
        org, which filters to that no-org bucket (records whose own
        organization_id is None), NOT every tenant's data. Only leaving
        org_id unset at all (the default) returns the unscoped,
        cross-tenant view, and that must stay reserved for internal/
        system purposes that never surface raw content to an end user."""
        with self._lock:
            records = self._records if org_id is _UNSCOPED else [
                r for r in self._records if r.organization_id == org_id
            ]
            return list(records[-n:])

    def for_agent(self, name: str) -> list[ExecutionRecord]:
        with self._lock:
            return [r for r in self._records if r.agent == name]

    def stats(self, name: str) -> AgentStats:
        records = self.for_agent(name)
        return _compute_stats(name, records)

    def global_stats(self) -> list[AgentStats]:
        with self._lock:
            by_agent: dict[str, list[ExecutionRecord]] = {}
            for r in self._records:
                by_agent.setdefault(r.agent, []).append(r)
        return sorted(
            [_compute_stats(n, recs) for n, recs in by_agent.items()],
            key=lambda s: s.call_count,
            reverse=True,
        )

    def underperformers(self, threshold: float = 0.7, min_calls: int = 3) -> list[AgentStats]:
        return [
            s for s in self.global_stats()
            if s.call_count >= min_calls and s.success_rate < threshold
        ]

    def total_count(self) -> int:
        with self._lock:
            return len(self._records)

    def to_dict_list(self, n: int = 100) -> list[dict]:
        return [r.to_dict() for r in self.recent(n)]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            tmp = _MEMORY_FILE.with_suffix(".tmp")
            with self._lock:
                data = [r.to_dict() for r in self._records]
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(_MEMORY_FILE)
        except Exception as exc:
            log.warning("agent memory persist failed: %s", exc)

    def _load(self) -> None:
        if not _MEMORY_FILE.exists():
            return
        try:
            raw = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
            self._records = [ExecutionRecord.from_dict(r) for r in raw]
            log.debug("agent memory loaded: %d records", len(self._records))
        except Exception as exc:
            log.warning("agent memory load failed: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_stats(name: str, records: list[ExecutionRecord]) -> AgentStats:
    if not records:
        return AgentStats(name=name, call_count=0, success_count=0, fail_count=0,
                          avg_ms=0.0, success_rate=1.0, last_called=None)
    successes = [r for r in records if r.success]
    return AgentStats(
        name         = name,
        call_count   = len(records),
        success_count= len(successes),
        fail_count   = len(records) - len(successes),
        avg_ms       = sum(r.duration_ms for r in records) / len(records),
        success_rate = len(successes) / len(records),
        last_called  = max(r.timestamp for r in records),
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_memory: AgentMemory | None = None


def get_memory() -> AgentMemory:
    global _memory
    if _memory is None:
        _memory = AgentMemory()
    return _memory
