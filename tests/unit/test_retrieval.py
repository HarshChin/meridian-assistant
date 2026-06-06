"""Retrieval tests: gold-query recall, abstention, and HNSW-vs-exact parity.

These require the committed index (``make ingest``) and load the local embedding model;
they are skipped if the index is absent so the keyless gate still runs everywhere.
"""

from __future__ import annotations

import pytest

from meridian.config import get_settings
from meridian.ingestion.chunker import Chunk
from meridian.retrieval.confidence import Confidence
from meridian.retrieval.embedder import embed_query
from meridian.retrieval.retriever import HybridRetriever
from meridian.retrieval.store import ChromaVectorStore, NumpyVectorStore

_INDEX = get_settings().index_dir
pytestmark = pytest.mark.skipif(
    not (_INDEX / "chunks.jsonl").exists(), reason="retrieval index not built (run `make ingest`)"
)


@pytest.fixture(scope="module")
def retriever() -> HybridRetriever:
    return HybridRetriever.load()


@pytest.mark.parametrize(
    ("query", "expected_doc"),
    [
        ("What time does the Herndon branch open on Saturday?", "branch_hours"),
        ("How much to replace a 40 gallon water heater?", "plumbing_pricing"),
        ("difference between the Gold and Platinum plans", "hvac_pricing"),
        ("Do you accept Zelle as payment?", "faq_payments"),
        ("Is there a surcharge for a Sunday appointment?", "hvac_pricing"),
        ("What is the no-show cancellation fee?", "cancellation_policy"),
        ("Do you service plumbing in ZIP 20147?", "service_area_north"),
        ("Is my dripping faucet still under warranty?", "warranty_terms"),
    ],
)
def test_gold_queries_retrieve_expected_doc(
    retriever: HybridRetriever, query: str, expected_doc: str
) -> None:
    results, _ = retriever.search(query)
    docs = [r.chunk.doc_id for r in results]
    assert expected_doc in docs, f"expected {expected_doc} in top-k, got {docs}"


def test_in_corpus_is_confident(retriever: HybridRetriever) -> None:
    _, conf = retriever.search("What is the no-show cancellation fee?")
    assert conf in (Confidence.HIGH, Confidence.MEDIUM)


def test_off_corpus_abstains(retriever: HybridRetriever) -> None:
    _, conf = retriever.search("What is the weather in Paris tomorrow?")
    assert conf is Confidence.LOW


def test_hnsw_matches_exact_topk() -> None:
    lines = (_INDEX / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    chunks = [Chunk.model_validate_json(line) for line in lines if line.strip()]
    ids = [c.chunk_id for c in chunks]
    numpy_store = NumpyVectorStore.load(_INDEX / "dense.npy", ids)
    chroma_store = ChromaVectorStore.load(_INDEX / "chroma")
    query_vec = embed_query("cancellation fee for a no-show")
    numpy_top = [cid for cid, _ in numpy_store.search(query_vec, 5)]
    chroma_top = [cid for cid, _ in chroma_store.search(query_vec, 5)]
    assert numpy_top == chroma_top
