"""
Layered Memory System.

Layers:
  ShortTermMemory   — in-process ring buffer (last 200 items, TTL 30 min)
  LongTermMemory    — JSON-persisted store with semantic search (TF-IDF)
  LayeredMemory     — unified facade: writes to both, queries across both

Semantic search uses lightweight TF-IDF (no external vector DB required).
Replace _score() with an embedding call when a vector DB is available.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_TMPDIR = Path(os.getenv("TMPDIR", "/tmp") if os.name != "nt" else os.getenv("TEMP", "C:\\Temp"))
_LT_PATH  = _TMPDIR / "axon-longterm-memory.json"
_ST_TTL   = 30 * 60   # 30 minutes
_ST_MAX   = 200
_LT_MAX   = 5_000


# ── Memory record ─────────────────────────────────────────────────────────────

@dataclass
class MemoryItem:
    id        : str
    layer     : str                  # "short" | "long"
    kind      : str                  # "execution" | "reflection" | "error" | "learning" | "task"
    content   : str                  # searchable text summary
    data      : dict = field(default_factory=dict)
    tags      : list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    agent     : Optional[str] = None
    success   : Optional[bool] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Short-term memory ─────────────────────────────────────────────────────────

class ShortTermMemory:
    """Rolling in-memory buffer with TTL expiry."""

    def __init__(self, max_items: int = _ST_MAX, ttl_s: float = _ST_TTL) -> None:
        self._lock    = threading.Lock()
        self._items   : deque[MemoryItem] = deque(maxlen=max_items)
        self._ttl     = ttl_s

    def add(self, item: MemoryItem) -> None:
        with self._lock:
            self._items.append(item)

    def recent(self, n: int = 50) -> list[MemoryItem]:
        now = time.time()
        with self._lock:
            live = [i for i in self._items if (now - i.created_at) < self._ttl]
            return list(live)[-n:]

    def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        results = self.recent(self._items.maxlen or _ST_MAX)
        scored  = [(i, _score(query, i.content)) for i in results]
        scored.sort(key=lambda x: -x[1])
        return [i for i, s in scored[:limit] if s > 0]

    @property
    def count(self) -> int:
        return len(self._items)


# ── Long-term memory ──────────────────────────────────────────────────────────

class LongTermMemory:
    """JSON-persisted store with simple TF-IDF search."""

    def __init__(self, path: Path = _LT_PATH) -> None:
        self._lock  = threading.Lock()
        self._path  = path
        self._items : list[MemoryItem] = []
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._items = [MemoryItem(**r) for r in raw]
        except Exception:
            self._items = []

    def _save(self) -> None:
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps([i.to_dict() for i in self._items]))
            self._dirty = False
        except OSError:
            pass

    def add(self, item: MemoryItem) -> None:
        with self._lock:
            self._items.append(item)
            if len(self._items) > _LT_MAX:
                self._items = self._items[-_LT_MAX:]
            self._dirty = True
            self._save()

    def search(self, query: str, limit: int = 10,
               kind: Optional[str] = None) -> list[MemoryItem]:
        with self._lock:
            items = self._items if not kind else [i for i in self._items if i.kind == kind]
        scored = [(i, _score(query, i.content + " " + " ".join(i.tags))) for i in items]
        scored.sort(key=lambda x: -x[1])
        return [i for i, s in scored[:limit] if s > 0]

    def recent(self, n: int = 50,
               kind: Optional[str] = None) -> list[MemoryItem]:
        with self._lock:
            items = self._items if not kind else [i for i in self._items if i.kind == kind]
        return list(items)[-n:]

    @property
    def count(self) -> int:
        return len(self._items)


# ── TF-IDF scorer (no external deps) ─────────────────────────────────────────

_RE_WORD = re.compile(r"\w+")

def _tokenise(text: str) -> list[str]:
    return _RE_WORD.findall(text.lower())

def _tf(tokens: list[str]) -> dict[str, float]:
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    n = len(tokens) or 1
    return {t: c / n for t, c in freq.items()}

def _score(query: str, document: str) -> float:
    """Simple TF-based cosine similarity (no IDF — fast, good enough for short docs)."""
    q_tokens = _tokenise(query)
    d_tokens = _tokenise(document)
    if not q_tokens or not d_tokens:
        return 0.0
    d_tf = _tf(d_tokens)
    matches = sum(d_tf.get(t, 0.0) for t in q_tokens)
    norm    = math.sqrt(len(q_tokens)) or 1.0
    return matches / norm


# ── Unified facade ────────────────────────────────────────────────────────────

class LayeredMemory:
    """
    Writes to both layers.
    Searches short-term first, fills remaining results from long-term.
    """

    def __init__(self) -> None:
        self.short  = ShortTermMemory()
        self.long   = LongTermMemory()

    def add(self, item: MemoryItem) -> None:
        item.layer = "short"
        self.short.add(item)
        # Promote to long-term immediately (acts as redundant but searchable store)
        lt_item = MemoryItem(**{**item.to_dict(), "layer": "long"})
        self.long.add(lt_item)

    def search(self, query: str, limit: int = 20,
               kind: Optional[str] = None) -> list[MemoryItem]:
        seen  : set[str] = set()
        results: list[MemoryItem] = []
        for item in self.short.search(query, limit):
            if item.id not in seen:
                seen.add(item.id)
                results.append(item)
        for item in self.long.search(query, limit, kind=kind):
            if item.id not in seen and len(results) < limit:
                seen.add(item.id)
                results.append(item)
        return results[:limit]

    def recent(self, n: int = 50, kind: Optional[str] = None) -> list[MemoryItem]:
        return self.long.recent(n, kind=kind)

    @property
    def stats(self) -> dict:
        return {
            "short_term": self.short.count,
            "long_term" : self.long.count,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_memory: LayeredMemory | None = None


def get_layered_memory() -> LayeredMemory:
    global _memory
    if _memory is None:
        _memory = LayeredMemory()
    return _memory
