"""Service-area coverage reproduces every documented edge — keyless, deterministic.

``check_coverage`` applies deterministic ZIP-range logic to ``data/extracted/coverage.json``,
which is compiled from the service-area documents by :mod:`meridian.extraction` (no hand-authored
facts). No LLM or retrieval runs here — a retrieval glitch can never change who we book. Covers
in-range, the ZIP-range *gaps* a naive min-max parser would wrongly include, pending,
sub-contracted, partner-referral, coordination, and document-faithful out-of-area escalation.
"""

from __future__ import annotations

import pytest

from meridian.domain.enums import ServiceType
from meridian.knowledge.coverage import check_coverage

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
def test_coverage_edges(
    zip_code: str,
    service: str,
    eligibility: str,
    flag: tuple[str, object] | None,
    region: str | None,
) -> None:
    decision = check_coverage(zip_code, ServiceType(service))
    assert decision.eligibility.value == eligibility
    assert (decision.region.value if decision.region else None) == region
    if flag is not None:
        name, expected = flag
        actual = getattr(decision.flags, name)
        if isinstance(expected, str):
            assert isinstance(actual, str) and expected.lower() in actual.lower()
        else:
            assert actual == expected


def test_documented_source_for_covered_zip() -> None:
    decision = check_coverage("22032", ServiceType.HVAC)
    assert decision.source == "documented"
    assert decision.primary_branch == "Falls Church"
    assert decision.county == "Fairfax"


def test_invalid_zip_is_unknown() -> None:
    assert check_coverage("2204", ServiceType.HVAC).eligibility.value == "unknown"
    assert check_coverage("abcde", ServiceType.HVAC).source == "none"
