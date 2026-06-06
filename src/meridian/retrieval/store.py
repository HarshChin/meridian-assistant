"""Vector stores behind a swappable protocol.

Default is **Chroma** (embedded, persistent); a **NumPy exact** store is kept as a
zero-dependency alternative and as the reference for the HNSW-vs-exact parity test. At
this corpus size HNSW returns effectively-exact top-k; the interface is the seam to a
managed vector DB at production scale.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Protocol

import numpy as np

_COLLECTION = "meridian"


class VectorStore(Protocol):
    """A nearest-neighbour store over chunk embeddings."""

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Return the top-``k`` ``(chunk_id, cosine_similarity)`` for a query vector."""
        ...


class NumpyVectorStore:
    """Exact brute-force cosine search (vectors are pre-normalised)."""

    def __init__(self, chunk_ids: list[str], embeddings: np.ndarray) -> None:
        """Initialise with aligned ``chunk_ids`` and a normalised embedding matrix."""
        self._ids = chunk_ids
        self._emb = embeddings

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Return exact top-``k`` by cosine (== dot, since normalised)."""
        sims = self._emb @ query_vec
        order = np.argsort(-sims)[:k]
        return [(self._ids[int(i)], float(sims[int(i)])) for i in order]

    def save(self, path: Path) -> None:
        """Persist the embedding matrix to ``path`` (``.npy``)."""
        np.save(path, self._emb)

    @classmethod
    def load(cls, path: Path, chunk_ids: list[str]) -> NumpyVectorStore:
        """Load the embedding matrix and pair it with ``chunk_ids``."""
        return cls(chunk_ids, np.load(path))


class ChromaVectorStore:
    """Embedded, persistent Chroma collection (HNSW, cosine)."""

    def __init__(self, collection: Any) -> None:
        """Wrap an existing Chroma collection handle."""
        self._col = collection

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Query Chroma and convert cosine distance to similarity."""
        res = self._col.query(query_embeddings=[query_vec.tolist()], n_results=k)
        ids = res["ids"][0]
        distances = res["distances"][0]
        return [(cid, 1.0 - float(dist)) for cid, dist in zip(ids, distances, strict=False)]

    @classmethod
    def build(
        cls,
        path: Path,
        chunk_ids: list[str],
        embeddings: np.ndarray,
        texts: list[str],
        metadatas: list[dict[str, Any]],
    ) -> ChromaVectorStore:
        """Create a fresh persistent collection and add the embeddings."""
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        with contextlib.suppress(Exception):
            client.delete_collection(_COLLECTION)
        collection = client.create_collection(_COLLECTION, metadata={"hnsw:space": "cosine"})
        collection.add(
            ids=chunk_ids,
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=metadatas,  # type: ignore[arg-type]  # chromadb's Metadata type is stricter
        )
        return cls(collection)

    @classmethod
    def load(cls, path: Path) -> ChromaVectorStore:
        """Open the persistent collection at ``path``."""
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        return cls(client.get_collection(_COLLECTION))
