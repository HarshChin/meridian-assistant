"""Local ONNX embeddings via fastembed (``bge-base-en-v1.5``).

Free, offline, reproducible. bge uses asymmetric query/document encoding, which fastembed
exposes via ``query_embed`` vs ``embed``; vectors are L2-normalised so cosine == dot.
"""

from __future__ import annotations

import functools

import numpy as np
from fastembed import TextEmbedding

from ..config import get_settings


@functools.lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    """Load and cache the embedding model (downloads the ONNX weights on first use)."""
    return TextEmbedding(model_name=get_settings().embed_model)


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalise rows so dot product equals cosine similarity."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.clip(norms, 1e-12, None)).astype(np.float32)


def embed_documents(texts: list[str]) -> np.ndarray:
    """Embed passages; returns an ``(n, dim)`` normalised float32 matrix."""
    vectors = np.array(list(_model().embed(texts)), dtype=np.float32)
    return _normalize(vectors)


def embed_query(text: str) -> np.ndarray:
    """Embed a query (with bge's query instruction); returns a ``(dim,)`` normalised vector."""
    vector = np.array(next(iter(_model().query_embed(text))), dtype=np.float32)
    return _normalize(vector[np.newaxis, :])[0]
