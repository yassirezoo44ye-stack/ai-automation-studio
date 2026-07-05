"""
KnowledgeEngine — semantic search, chunking, citation, and ranking.

Backed by EmbeddingsService; vector-DB-ready (swap _search_backend).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from ..events.bus    import EventBus
from ..events.events import DocumentIngested, KnowledgeSearched

if TYPE_CHECKING:
    from ..embeddings.service import EmbeddingsService


_DEFAULT_CHUNK_SIZE  = 512    # chars
_DEFAULT_CHUNK_OVERLAP = 64


@dataclass
class Document:
    id:          str
    content:     str
    source:      str = ""
    metadata:    dict[str, Any] = field(default_factory=dict)
    chunks:      list[str]      = field(default_factory=list)
    embeddings:  list[list[float]] = field(default_factory=list)
    ingested_at: float = field(default_factory=time.time)


@dataclass
class SearchResult:
    doc_id:    str
    chunk:     str
    source:    str
    score:     float
    citation:  str    # formatted "Source: {source} (chunk {i})"
    rank:      int


class KnowledgeEngine:
    """
    In-process knowledge base with semantic search.

    For production, replace `_search_backend` with a pgvector / Pinecone call.
    """

    def __init__(
        self,
        embeddings: "EmbeddingsService",
        bus:        EventBus,
        chunk_size:    int = _DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self._embeddings    = embeddings
        self._bus           = bus
        self._chunk_size    = chunk_size
        self._chunk_overlap = chunk_overlap
        self._store: dict[str, Document] = {}

    async def ingest(
        self,
        content:  str,
        source:   str = "",
        metadata: Optional[dict[str, Any]] = None,
        doc_id:   Optional[str] = None,
    ) -> Document:
        chunks = self._chunk(content)
        embeddings: list[list[float]] = []

        embed_results = await self._embeddings.embed_many(chunks)
        embeddings = [r.vector for r in embed_results]

        doc = Document(
            id=doc_id or str(uuid.uuid4()),
            content=content,
            source=source,
            metadata=metadata or {},
            chunks=chunks,
            embeddings=embeddings,
        )
        self._store[doc.id] = doc

        await self._bus.emit(DocumentIngested(
            doc_id=doc.id,
            chunk_count=len(chunks),
            source=source,
        ))
        return doc

    async def search(
        self,
        query:   str,
        top_k:   int   = 5,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        t0 = time.perf_counter()

        query_emb = await self._embeddings.embed(query)
        results: list[tuple[float, str, int, str]] = []   # (score, doc_id, chunk_idx, chunk)

        for doc in self._store.values():
            for i, (chunk_vec, chunk_text) in enumerate(zip(doc.embeddings, doc.chunks)):
                score = self._cosine(query_emb.vector, chunk_vec)
                if score >= min_score:
                    results.append((score, doc.id, i, chunk_text, doc.source))

        results.sort(key=lambda x: x[0], reverse=True)
        top = results[:top_k]

        search_results = [
            SearchResult(
                doc_id=r[1],
                chunk=r[3],
                source=r[4],
                score=round(r[0], 4),
                citation=f"Source: {r[4] or r[1]} (chunk {r[2] + 1})",
                rank=rank + 1,
            )
            for rank, r in enumerate(top)
        ]

        latency_ms = (time.perf_counter() - t0) * 1000
        await self._bus.emit(KnowledgeSearched(
            query=query[:200],
            result_count=len(search_results),
            latency_ms=latency_ms,
        ))
        return search_results

    def delete(self, doc_id: str) -> bool:
        return bool(self._store.pop(doc_id, None))

    def list_documents(self) -> list[dict[str, Any]]:
        return [
            {
                "id":     doc.id,
                "source": doc.source,
                "chunks": len(doc.chunks),
                "at":     doc.ingested_at,
            }
            for doc in self._store.values()
        ]

    def diagnostics(self) -> dict[str, Any]:
        total_chunks = sum(len(d.chunks) for d in self._store.values())
        return {
            "documents":   len(self._store),
            "chunks":      total_chunks,
            "chunk_size":  self._chunk_size,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _chunk(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._chunk_size
            chunks.append(text[start:end])
            start = end - self._chunk_overlap
        return chunks or [text]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot  = sum(x * y for x, y in zip(a, b))
        norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
        return dot / norm if norm else 0.0
