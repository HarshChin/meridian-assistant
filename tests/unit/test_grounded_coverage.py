"""Grounded service-area resolver: reproduces every documented coverage edge, keyless.

This is the generalization-critical test: coverage is derived by an LLM extracting structure
from the corpus (no hand-authored facts), then deterministic ZIP-membership logic. It replays
the committed extraction cache, so it runs without an API key — but proves the grounded path
yields document-faithful decisions (gaps, pending, sub-contracted, partner-referral,
coordination, and out-of-area escalation).
"""

from __future__ import annotations

import pytest

from meridian.config import get_settings
from meridian.domain.enums import ServiceType
from meridian.extraction.service_area import ServiceAreaResolver
from meridian.llm.client import LLMClient
from meridian.retrieval.retriever import HybridRetriever

_SETTINGS = get_settings()
_INDEX = _SETTINGS.index_dir
_CACHE = _SETTINGS.llm_cache_dir

pytestmark = pytest.mark.skipif(
    not (_INDEX / "chunks.jsonl").exists() or not any(_CACHE.glob("*.json")),
    reason="needs committed index + LLM cache (run `make ingest` / build the extraction cache)",
)


@pytest.fixture(scope="module")
def resolver() -> ServiceAreaResolver:
    return ServiceAreaResolver(HybridRetriever.load(), LLMClient())


# zip, service, expected eligibility, (flag_name, expected_value) or None, expected region
_EDGES = [
    ("22032", "hvac", "yes", None, "north"),
    ("22040", "hvac", "unknown", None, None),  # Fairfax gap — not covered
    ("22210", "hvac", "unknown", None, None),  # Arlington gap 22210-12 — not covered
    ("22213", "hvac", "yes", None, "north"),  # Arlington singleton
    ("22305", "electrical", "pending", None, "north"),  # Alexandria electrical pending
    ("22305", "hvac", "yes", None, "north"),
    ("20147", "plumbing", "yes", ("sub_contracted", True), "north"),
    ("20147", "plumbing", "yes", ("same_day_blocked", True), "north"),
    ("20147", "electrical", "no", None, "north"),
    ("20165", "electrical", "no", None, "north"),  # Loudoun singleton
    ("20814", "electrical", "yes", None, "central"),
    ("20708", "electrical", "no", ("refer_partner", "EcoPower"), "central"),
    ("20708", "hvac", "yes", None, "central"),
    ("20742", "hvac", "yes", ("coordination_required", True), "central"),  # UMD
    ("21045", "hvac", "yes", None, "central"),  # Howard singleton
    ("20110", "hvac", "unknown", None, None),  # Manassas — not listed
    ("21401", "hvac", "unknown", None, None),  # Annapolis/South — no coverage doc
    ("22046", "hvac", "unknown", None, None),  # Falls Church city — document-faithful escalate
]


@pytest.mark.parametrize(("zip_code", "service", "eligibility", "flag", "region"), _EDGES)
def test_grounded_coverage_edges(
    resolver: ServiceAreaResolver,
    zip_code: str,
    service: str,
    eligibility: str,
    flag: tuple[str, object] | None,
    region: str | None,
) -> None:
    decision = resolver.check(zip_code, ServiceType(service))
    assert decision.eligibility.value == eligibility
    assert (decision.region.value if decision.region else None) == region
    if flag is not None:
        name, expected = flag
        actual = getattr(decision.flags, name)
        if isinstance(expected, str):
            assert isinstance(actual, str) and expected.lower() in actual.lower()
        else:
            assert actual == expected


def test_invalid_zip_is_unknown(resolver: ServiceAreaResolver) -> None:
    decision = resolver.check("2204", ServiceType.HVAC)
    assert decision.eligibility.value == "unknown"
    assert decision.source == "none"
