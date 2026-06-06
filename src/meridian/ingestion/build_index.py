"""Build the committed retrieval index from the corpus markdown.

Run ``python -m meridian.ingestion.build_index`` (or ``make ingest``). Writes a flat
``chunks.jsonl`` (the chunk source of truth), the dense embeddings (NumPy + a Chroma
collection), and a ``manifest.json`` recording the embed model + a corpus hash for
staleness. Document-agnostic: it indexes whatever markdown is in ``data/corpus``.
"""

from __future__ import annotations

import hashlib
import json
import shutil

from ..config import get_settings
from ..retrieval.embedder import embed_documents
from ..retrieval.store import ChromaVectorStore, NumpyVectorStore
from .chunker import chunk_corpus


def build_index() -> int:
    """Chunk the corpus, embed, and persist the index. Returns the chunk count."""
    settings = get_settings()
    index_dir = settings.index_dir
    index_dir.mkdir(parents=True, exist_ok=True)

    chunks = chunk_corpus()
    if not chunks:
        raise RuntimeError("No chunks produced - did you run the extractor (data/corpus empty)?")
    ids = [c.chunk_id for c in chunks]
    texts = [c.text for c in chunks]
    embeddings = embed_documents(texts)

    (index_dir / "chunks.jsonl").write_text(
        "\n".join(c.model_dump_json() for c in chunks) + "\n", encoding="utf-8"
    )
    NumpyVectorStore(ids, embeddings).save(index_dir / "dense.npy")

    chroma_dir = index_dir / "chroma"
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)
    ChromaVectorStore.build(
        chroma_dir,
        ids,
        embeddings,
        texts,
        [{"doc_id": c.doc_id, "section": c.section} for c in chunks],
    )

    corpus_hash = hashlib.sha256(" ".join(texts).encode("utf-8")).hexdigest()[:16]
    manifest = {
        "embed_model": settings.embed_model,
        "n_chunks": len(chunks),
        "n_docs": len({c.doc_id for c in chunks}),
        "corpus_hash": corpus_hash,
    }
    (index_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return len(chunks)


def main() -> None:
    """CLI entry point: build the index and report the chunk count."""
    count = build_index()
    print(f"indexed {count} chunks into {get_settings().index_dir}")  # noqa: T201


if __name__ == "__main__":
    main()
