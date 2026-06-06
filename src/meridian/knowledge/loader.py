"""Load compiled knowledge records from ``data/extracted`` (keyless; no LLM at runtime).

These records are produced from the source documents by ``meridian.extraction.compile`` and
committed. Runtime loads them and applies deterministic logic, so booking-critical facts are
exact, reproducible, and immune to retrieval drift. Adding documents → re-run the compile
step; this layer is unchanged.
"""

from __future__ import annotations

import functools
import json
from typing import Any, TypeVar

from pydantic import BaseModel

from ..config import get_settings
from ..extraction.schemas import BranchDirectory, FeeSchedule, ServiceAreaExtraction

T = TypeVar("T", bound=BaseModel)


class KnowledgeNotCompiledError(RuntimeError):
    """Raised when a compiled knowledge record is missing (run the compile step)."""


def _load(name: str, model: type[T]) -> T:
    """Load and validate a compiled record by name."""
    path = get_settings().data_dir / "extracted" / f"{name}.json"
    if not path.exists():
        raise KnowledgeNotCompiledError(
            f"Missing {path}. Run `python -m meridian.extraction.compile` to compile knowledge."
        )
    return model.model_validate_json(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def load_coverage() -> ServiceAreaExtraction:
    """Return the compiled service-area coverage record."""
    return _load("coverage", ServiceAreaExtraction)


@functools.lru_cache(maxsize=1)
def load_fees() -> FeeSchedule:
    """Return the compiled fee schedule."""
    return _load("fees", FeeSchedule)


@functools.lru_cache(maxsize=1)
def load_branches() -> BranchDirectory:
    """Return the compiled branch directory."""
    return _load("branches", BranchDirectory)


@functools.lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    """Return the compiled-knowledge provenance manifest (model, corpus hash, source docs)."""
    path = get_settings().data_dir / "extracted" / "manifest.json"
    if not path.exists():
        raise KnowledgeNotCompiledError(
            f"Missing {path}. Run `python -m meridian.extraction.compile`."
        )
    return dict(json.loads(path.read_text(encoding="utf-8")))


def fee_source_docs() -> list[str]:
    """Return the documents the fee schedule was compiled from (a data-derived citation)."""
    try:
        capabilities = load_manifest().get("capabilities", {})
    except KnowledgeNotCompiledError:
        return []
    fees = capabilities.get("fees", {}) if isinstance(capabilities, dict) else {}
    docs = fees.get("source_docs", []) if isinstance(fees, dict) else []
    return [str(doc) for doc in docs]


def reset_caches() -> None:
    """Clear the loader caches (call after recompiling or repointing the data directory)."""
    load_coverage.cache_clear()
    load_fees.cache_clear()
    load_branches.cache_clear()
    load_manifest.cache_clear()
