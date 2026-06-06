"""Generalization: a NEVER-SEEN document compiles correctly with the SAME schema + prompt.

This is the proof the knowledge pipeline is not biased to the 13 sample PDFs. A synthetic
service-area document for a fictional region — with the same PDF glyph artifacts a real extract
shows (✓→"3", ✗→"7"), an inline "Pending", a "Sub-contracted", a partner referral, a ZIP gap,
and a coordination note — is extracted by the UNCHANGED coverage extractor into correct
structured facts, and the deterministic ZIP logic then makes document-faithful decisions.

It replays the committed LLM cache, so it runs keyless; nothing about the extractor, schema, or
prompts was specialised for this document.
"""

from __future__ import annotations

import pytest

from meridian.config import get_settings
from meridian.domain.enums import ServiceType
from meridian.extraction.extractors import _COVERAGE_SYSTEM
from meridian.extraction.schemas import ServiceAreaExtraction
from meridian.knowledge.coverage import _TOKEN_TO_ELIGIBILITY, _decide
from meridian.llm.client import LLMClient

pytestmark = pytest.mark.skipif(
    not any(get_settings().llm_cache_dir.glob("*.json")),
    reason="needs the committed LLM cache (keyless replay)",
)

# A fictional West region the system has never seen, in the same garbled-table form a PDF
# extract produces ("3" = ✓ available, "7" = ✗ not available; explicit words win).
_SYNTHETIC_DOC = """[source: service_area_west v1.0 — Covered ZIP Codes]
# Service Area — West Region

ZIP-code coverage for Shenandoah, Clarke, and Warren counties.
## Covered ZIP Codes
County ZIP Codes HVAC Plumbing Electrical
Shenandoah 22810-22815, 22820 3 3 7
Clarke 22600-22610 3 Pending (Q3) 3
Warren 22630, 22640 7 3 Sub-contracted
## Important Notes
Electrical is not licensed in Shenandoah County; refer customers to sister contractor VoltPro.
Warren County (22640) requires facilities-office co-ordination before booking.
"""


@pytest.fixture(scope="module")
def extraction() -> ServiceAreaExtraction:
    return LLMClient().structured(_COVERAGE_SYSTEM, _SYNTHETIC_DOC, ServiceAreaExtraction)


def test_all_new_counties_extracted(extraction: ServiceAreaExtraction) -> None:
    counties = {c.county.lower() for c in extraction.counties}
    assert {"shenandoah", "clarke", "warren"} <= counties


def test_glyph_and_word_tokens(extraction: ServiceAreaExtraction) -> None:
    by_county = {c.county.lower(): c for c in extraction.counties}
    assert by_county["shenandoah"].hvac == "available"  # "3" → ✓
    assert by_county["shenandoah"].electrical == "not_available"  # "7" → ✗
    assert by_county["clarke"].plumbing == "pending"  # "Pending (Q3)"
    assert by_county["warren"].hvac == "not_available"  # "7"
    assert by_county["warren"].electrical == "subcontracted"  # "Sub-contracted"


def test_zip_gap_preserved(extraction: ServiceAreaExtraction) -> None:
    segs = {c.county.lower(): c.zip_segments for c in extraction.counties}["shenandoah"]
    # 22810-22815 + 22820: 22816 is a gap (not covered); 22812 is covered.
    assert any(s.low <= 22812 <= s.high for s in segs)
    assert not any(s.low <= 22816 <= s.high for s in segs)


def test_partner_and_coordination_captured(extraction: ServiceAreaExtraction) -> None:
    by_county = {c.county.lower(): c for c in extraction.counties}
    assert (by_county["shenandoah"].refer_partner or "").lower().find("voltpro") >= 0
    assert 22640 in by_county["warren"].coordination_zips


def test_deterministic_decision_on_unseen_region(extraction: ServiceAreaExtraction) -> None:
    # The SAME deterministic logic used for the real corpus applies to the unseen extraction.
    warren = next(c for c in extraction.counties if c.county.lower() == "warren")
    decision = _decide("22640", 22640, ServiceType.HVAC, warren, extraction)
    assert decision.eligibility is _TOKEN_TO_ELIGIBILITY["not_available"]
    assert decision.flags.coordination_required is True
