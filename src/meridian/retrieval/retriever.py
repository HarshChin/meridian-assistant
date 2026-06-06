"""Hybrid retriever: dense + BM25 fused with Reciprocal Rank Fusion (RRF).

RRF is rank-based (scale-free), so it combines the two very different score distributions
robustly and deterministically (ties broken by chunk_id). The retriever also reports a
confidence band so the agent can abstain → hand off when the corpus likely can't answer.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..config import get_settings
from ..ingestion.chunker import Chunk
from .bm25 import BM25Index
from .confidence import Confidence, assess
from .embedder import embed_query
from .store import ChromaVectorStore, VectorStore


class RetrievedChunk(BaseModel):
    """A chunk returned by retrieval, with its fused score + best dense cosine."""

    chunk: Chunk
    score: float
    dense_cosine: float


def _rrf(rankings: list[list[str]], k: int) -> dict[str, float]:
    """Reciprocal Rank Fusion: ``score(id) = Σ 1 / (k + rank)`` across rankings."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return fused


class HybridRetriever:
    """Loads the committed index and answers queries via dense+BM25 RRF fusion."""

    def __init__(self, chunks: list[Chunk], vector_store: VectorStore, bm25: BM25Index) -> None:
        """Initialise from chunks, a dense vector store, and a BM25 index."""
        self._by_id = {c.chunk_id: c for c in chunks}
        self._vector_store = vector_store
        self._bm25 = bm25

    @classmethod
    def load(cls) -> HybridRetriever:
        """Load chunks + the Chroma store from ``data/index`` and rebuild BM25."""
        index_dir = get_settings().index_dir
        lines = (index_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        chunks = [Chunk.model_validate_json(line) for line in lines if line.strip()]
        vector_store = ChromaVectorStore.load(index_dir / "chroma")
        bm25 = BM25Index([c.chunk_id for c in chunks], [c.text for c in chunks])
        return cls(chunks, vector_store, bm25)

    def search(
        self, query: str, k: int | None = None, candidate_k: int | None = None
    ) -> tuple[list[RetrievedChunk], Confidence]:
        """Return the fused top-``k`` chunks for ``query`` plus a confidence band."""
        settings = get_settings()
        top_k = k or settings.top_k
        cand_k = candidate_k or settings.candidate_k

        query_vec = embed_query(query)
        dense = self._vector_store.search(query_vec, cand_k)
        sparse = self._bm25.search(query, cand_k)
        dense_cos = dict(dense)

        fused = _rrf([[cid for cid, _ in dense], [cid for cid, _ in sparse]], settings.rrf_k)
        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
        results = [
            RetrievedChunk(
                chunk=self._by_id[cid], score=score, dense_cosine=dense_cos.get(cid, 0.0)
            )
            for cid, score in ranked
            if cid in self._by_id
        ]
        top_cosine = max((r.dense_cosine for r in results), default=0.0)
        return results, assess(top_cosine)
