"""BM25 lexical retrieval over chunk text.

Digits are kept in tokens because ZIPs, prices, and amperages (``200A``) are load-bearing
for this corpus — lexical match on them is exactly where dense embeddings are weakest.
"""

from __future__ import annotations

import re

import numpy as np
from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, alphanumeric tokens (digits preserved)."""
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """An in-memory BM25 index over a fixed set of chunks (rebuilt cheaply at load)."""

    def __init__(self, chunk_ids: list[str], texts: list[str]) -> None:
        """Build the index from aligned ``chunk_ids`` and ``texts``."""
        self._ids = chunk_ids
        self._bm25 = BM25Okapi([tokenize(t) for t in texts])

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return the top-``k`` ``(chunk_id, score)`` for ``query`` (descending)."""
        scores = self._bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)[:k]
        return [(self._ids[int(i)], float(scores[int(i)])) for i in order]
