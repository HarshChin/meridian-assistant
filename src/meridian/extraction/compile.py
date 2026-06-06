"""Knowledge compilation: extract capability records from the corpus into ``data/extracted``.

Run with ``python -m meridian.extraction.compile [label]`` (needs ANTHROPIC_API_KEY only for a
cold cache; the committed LLM cache makes re-runs keyless). Writes one JSON record per
booking-critical capability plus a provenance manifest. Runtime loads these committed records
and never calls the LLM — so booking-critical facts are exact, reproducible, and immune to
retrieval drift. Adding documents = re-run ``ingest`` then this; nothing is hand-edited.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import get_settings
from ..llm.client import LLMClient
from ..retrieval.retriever import HybridRetriever
from .extractors import extract_branches, extract_coverage, extract_fees


def _corpus_hash() -> str | None:
    """Return the corpus hash recorded by the index build, if available."""
    manifest = get_settings().index_dir / "manifest.json"
    if manifest.exists():
        value = json.loads(manifest.read_text(encoding="utf-8")).get("corpus_hash")
        return str(value) if value is not None else None
    return None


def compile_knowledge() -> Path:
    """Extract every capability record into ``data/extracted`` and write a manifest.

    The manifest's provenance is fully deterministic (model + corpus hash), so re-running this
    step reproduces every artifact — including the manifest — byte-for-byte. The build never
    reads the wall clock.

    Returns:
        The output directory holding the compiled records + ``manifest.json``.
    """
    settings = get_settings()
    out_dir = settings.data_dir / "extracted"
    out_dir.mkdir(parents=True, exist_ok=True)

    retriever = HybridRetriever.load()
    llm = LLMClient()

    capabilities: dict[str, dict[str, object]] = {}
    for name, extractor in (
        ("coverage", extract_coverage),
        ("fees", extract_fees),
        ("branches", extract_branches),
    ):
        record, docs = extractor(retriever, llm)
        (out_dir / f"{name}.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
        capabilities[name] = {"schema": type(record).__name__, "source_docs": docs}
        print(f"compiled {name}: {type(record).__name__} from {docs}")

    manifest = {
        "model": settings.agent_model,
        "corpus_hash": _corpus_hash(),
        "capabilities": capabilities,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    path = compile_knowledge()
    print(f"\nKnowledge compiled to {path}")
