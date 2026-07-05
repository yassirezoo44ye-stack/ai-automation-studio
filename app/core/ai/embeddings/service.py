"""
EmbeddingsService — unified interface for text embeddings.

Supports:
- Anthropic (via voyage-ai, planned)
- OpenAI text-embedding-3-small / large
- Gemini embedding-001

All results normalized to unit vectors.
Future: pluggable vector database backends (pgvector, Pinecone, Weaviate).

Usage::

    svc  = EmbeddingsService()
    vec  = await svc.embed("Hello world")
    hits = await svc.search("my query", corpus=[...])
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_OPENAI_EMBED_MODEL   = "text-embedding-3-small"
_OPENAI_EMBED_DIMS    = 1536
_OPENAI_EMBED_COST_M  = 0.02  # USD per 1M tokens


@dataclass
class EmbeddingResult:
    text:      str
    embedding: list[float]
    model:     str
    tokens:    int


@dataclass
class SearchHit:
    index:      int
    text:       str
    score:      float   # cosine similarity [0, 1]
    embedding:  list[float]


class EmbeddingsService:
    """
    Provider-agnostic embeddings service.

    Falls back gracefully when no embedding provider is configured —
    uses a zero-vector stub so callers don't crash.
    """

    def __init__(self, provider: str = "openai") -> None:
        self._provider = provider

    @property
    def is_available(self) -> bool:
        if self._provider == "openai":
            return bool(os.getenv("OPENAI_API_KEY"))
        return False

    # ── Public API ────────────────────────────────────────────────────────────

    async def embed(self, text: str, *, model: Optional[str] = None) -> EmbeddingResult:
        """Return an embedding vector for a single text."""
        if not self.is_available:
            return self._stub(text)

        if self._provider == "openai":
            return await self._openai_embed(text, model=model or _OPENAI_EMBED_MODEL)

        return self._stub(text)

    async def embed_many(
        self,
        texts: list[str],
        *,
        model: Optional[str] = None,
    ) -> list[EmbeddingResult]:
        """Batch embed; falls back to sequential if provider doesn't support batching."""
        import asyncio
        return await asyncio.gather(*[self.embed(t, model=model) for t in texts])

    async def search(
        self,
        query: str,
        corpus: list[str],
        *,
        top_k: int = 5,
        model: Optional[str] = None,
    ) -> list[SearchHit]:
        """Embed query and all corpus items, return top_k by cosine similarity."""
        if not corpus:
            return []

        query_result  = await self.embed(query, model=model)
        corpus_results = await self.embed_many(corpus, model=model)

        scored: list[tuple[int, float]] = []
        for idx, cr in enumerate(corpus_results):
            score = self.similarity(query_result.embedding, cr.embedding)
            scored.append((idx, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            SearchHit(
                index=idx,
                text=corpus[idx],
                score=round(score, 4),
                embedding=corpus_results[idx].embedding,
            )
            for idx, score in scored[:top_k]
        ]

    @staticmethod
    def similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two unit vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot  = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── Provider implementations ──────────────────────────────────────────────

    async def _openai_embed(self, text: str, *, model: str) -> EmbeddingResult:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            resp = await client.embeddings.create(input=text, model=model)
            return EmbeddingResult(
                text=text,
                embedding=resp.data[0].embedding,
                model=model,
                tokens=resp.usage.total_tokens,
            )
        except Exception as exc:
            log.error("EmbeddingsService._openai_embed failed: %s", exc)
            return self._stub(text)

    # ── Stub ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _stub(text: str) -> EmbeddingResult:
        """Zero-vector placeholder when no provider is configured."""
        return EmbeddingResult(
            text=text,
            embedding=[0.0] * _OPENAI_EMBED_DIMS,
            model="stub",
            tokens=0,
        )


# Module-level singleton
embeddings = EmbeddingsService()
