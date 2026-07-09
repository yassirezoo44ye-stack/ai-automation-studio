"""
Semantic Memory Layer — Layer 4 enhancement.

Adds a third tier to the existing 2-tier memory system (short + long-term):

  SemanticMemory — pgvector-backed vector store for embedding-based retrieval.

When pgvector is unavailable the layer falls back to TF-IDF silently.
Embeddings are generated via the AI Gateway (text-embedding-3-small by default).

Usage:
    from app.memory.semantic import get_semantic_memory
    mem = await get_semantic_memory(db_pool)
    await mem.store("session-1", "user asked about Python async", metadata={})
    results = await mem.search("how does asyncio work", top_k=5)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM   = 1536   # text-embedding-3-small output size


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SemanticResult:
    id         : str
    content    : str
    score      : float              # cosine similarity 0–1
    metadata   : dict[str, Any]     = field(default_factory=dict)
    created_at : float              = field(default_factory=time.time)
    layer      : str                = "semantic"

    def to_dict(self) -> dict:
        return {
            "id"        : self.id,
            "content"   : self.content,
            "score"     : round(self.score, 4),
            "metadata"  : self.metadata,
            "created_at": self.created_at,
            "layer"     : self.layer,
        }


# ── Embedding helpers ─────────────────────────────────────────────────────────

async def _embed_via_gateway(text: str, gateway) -> list[float]:
    """Call the AI Gateway embedding endpoint."""
    try:
        result = await gateway.embed(text=text, model=_EMBEDDING_MODEL)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("embedding") or result.get("data", [{}])[0].get("embedding", [])
    except Exception as exc:
        log.warning("semantic_memory embed failed: %s", exc)
    return []


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _tfidf_score(query: str, content: str) -> float:
    """Fast TF-IDF fallback (no deps)."""
    q_tokens = set(re.findall(r"\w+", query.lower())) if query else set()
    c_tokens = re.findall(r"\w+", content.lower())
    if not c_tokens or not q_tokens:
        return 0.0
    freq = {t: c_tokens.count(t) for t in q_tokens}
    score = sum(freq.values()) / max(len(c_tokens), 1)
    return min(score * 10, 1.0)



# ── pgvector schema setup ─────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS semantic_memory (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    embedding   vector({dim}),
    metadata    JSONB DEFAULT '{{}}'::jsonb,
    created_at  DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE INDEX IF NOT EXISTS idx_semantic_memory_embedding
    ON semantic_memory USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_semantic_memory_session
    ON semantic_memory (session_id);
""".format(dim=_EMBEDDING_DIM)


async def _ensure_schema(pool) -> bool:
    """Create the semantic_memory table + pgvector extension if needed."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
        return True
    except Exception as exc:
        log.warning("semantic_memory schema setup failed: %s — using TF-IDF fallback", exc)
        return False


# ── In-process fallback store ─────────────────────────────────────────────────

@dataclass
class _LocalItem:
    id         : str
    session_id : str
    content    : str
    embedding  : list[float]
    metadata   : dict
    created_at : float


class _LocalStore:
    """In-memory vector store — no DB needed."""

    def __init__(self) -> None:
        self._items: list[_LocalItem] = []

    def add(self, item: _LocalItem) -> None:
        self._items = [i for i in self._items if i.id != item.id]
        self._items.append(item)

    def search(self, query_vec: list[float], query_text: str,
               top_k: int, session_id: str = "") -> list[SemanticResult]:
        scored: list[tuple[float, _LocalItem]] = []
        for item in self._items:
            if session_id and item.session_id != session_id:
                continue
            if query_vec and item.embedding:
                score = _cosine(query_vec, item.embedding)
            else:
                score = _tfidf_score(query_text, item.content)
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SemanticResult(id=i.id, content=i.content, score=s,
                           metadata=i.metadata, created_at=i.created_at)
            for s, i in scored[:top_k]
        ]

    def delete(self, item_id: str) -> None:
        self._items = [i for i in self._items if i.id != item_id]

    def count(self) -> int:
        return len(self._items)


# ── Main class ────────────────────────────────────────────────────────────────

class SemanticMemory:
    """
    Vector-backed episodic memory.

    Prefers pgvector when a DB pool is provided.
    Falls back to in-process cosine similarity store.
    Embeddings generated via AI Gateway; falls back to no-embedding TF-IDF.
    """

    def __init__(self, pool=None, gateway=None) -> None:
        self._pool       = pool
        self._gateway    = gateway
        self._pgvector   = False      # set to True after schema verified
        self._local      = _LocalStore()
        self._init_task  : Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        if self._pool:
            self._pgvector = await _ensure_schema(self._pool)
            if self._pgvector:
                log.info("semantic_memory: using pgvector backend")
            else:
                log.info("semantic_memory: pgvector unavailable, using local store")
        else:
            log.info("semantic_memory: no DB pool, using local store")

    async def store(
        self,
        session_id : str,
        content    : str,
        metadata   : dict | None = None,
        item_id    : str | None  = None,
    ) -> str:
        """Embed and store content. Returns the item id."""
        if not item_id:
            digest   = hashlib.sha256(f"{session_id}:{content}".encode()).hexdigest()[:16]
            item_id  = f"sem-{digest}"

        embedding = []
        if self._gateway:
            embedding = await _embed_via_gateway(content, self._gateway)

        meta = metadata or {}
        now  = time.time()

        org_id = meta.get("organization_id")
        if org_id and embedding:
            try:
                from app.billing import get_usage_service
                await get_usage_service().record(org_id, "embeddings", 1, ref_type="semantic_memory", ref_id=item_id)
            except Exception:
                log.warning("embeddings usage record failed for org=%s", org_id, exc_info=True)

        if self._pgvector and self._pool:
            await self._pg_upsert(item_id, session_id, content, embedding, meta, now)
        else:
            self._local.add(_LocalItem(
                id=item_id, session_id=session_id, content=content,
                embedding=embedding, metadata=meta, created_at=now,
            ))
        return item_id

    async def search(
        self,
        query      : str,
        top_k      : int = 5,
        session_id : str = "",
        min_score  : float = 0.0,
    ) -> list[SemanticResult]:
        """Return top-k semantically similar items."""
        query_vec: list[float] = []
        if self._gateway:
            query_vec = await _embed_via_gateway(query, self._gateway)

        if self._pgvector and self._pool:
            results = await self._pg_search(query_vec, query, top_k, session_id)
        else:
            results = self._local.search(query_vec, query, top_k, session_id)

        return [r for r in results if r.score >= min_score]

    async def delete(self, item_id: str) -> None:
        if self._pgvector and self._pool:
            async with self._pool.acquire() as conn:
                await conn.execute("DELETE FROM semantic_memory WHERE id=$1", item_id)
        else:
            self._local.delete(item_id)

    async def count(self) -> int:
        if self._pgvector and self._pool:
            try:
                async with self._pool.acquire() as conn:
                    return await conn.fetchval("SELECT COUNT(*) FROM semantic_memory")
            except Exception:
                pass
        return self._local.count()

    # ── pgvector backend ───────────────────────────────────────────────────────

    async def _pg_upsert(self, item_id: str, session_id: str, content: str,
                         embedding: list[float], meta: dict, ts: float) -> None:
        vec = json.dumps(embedding) if embedding else None
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO semantic_memory (id, session_id, content, embedding, metadata, created_at)
                    VALUES ($1,$2,$3,$4::vector,$5,$6)
                    ON CONFLICT (id) DO UPDATE
                        SET content=$3, embedding=$4::vector, metadata=$5, created_at=$6
                    """,
                    item_id, session_id, content, vec, json.dumps(meta), ts,
                )
        except Exception as exc:
            log.warning("semantic_memory pg upsert failed: %s — falling back to local", exc)
            self._pgvector = False

    async def _pg_search(self, query_vec: list[float], query_text: str,
                         top_k: int, session_id: str) -> list[SemanticResult]:
        try:
            async with self._pool.acquire() as conn:
                if query_vec:
                    vec_str = json.dumps(query_vec)
                    where   = "WHERE session_id=$3" if session_id else ""
                    params  = [vec_str, top_k]
                    if session_id:
                        params.append(session_id)
                    rows = await conn.fetch(
                        f"""
                        SELECT id, content, metadata, created_at,
                               1 - (embedding <=> $1::vector) AS score
                        FROM semantic_memory
                        {where}
                        ORDER BY embedding <=> $1::vector
                        LIMIT $2
                        """,
                        *params,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, metadata, created_at, 0.5 AS score
                        FROM semantic_memory
                        ORDER BY created_at DESC LIMIT $1
                        """,
                        top_k,
                    )
            return [
                SemanticResult(
                    id=r["id"], content=r["content"],
                    score=float(r["score"]),
                    metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else dict(r["metadata"] or {}),
                    created_at=float(r["created_at"]),
                )
                for r in rows
            ]
        except Exception as exc:
            log.warning("semantic_memory pg search failed: %s", exc)
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: SemanticMemory | None = None


async def get_semantic_memory(pool=None, gateway=None) -> SemanticMemory:
    global _instance
    if _instance is None:
        _instance = SemanticMemory(pool=pool, gateway=gateway)
        await _instance.initialize()
    elif pool and _instance._pool is None:
        _instance._pool    = pool
        _instance._pgvector = await _ensure_schema(pool)
    elif gateway and _instance._gateway is None:
        _instance._gateway = gateway
    return _instance
