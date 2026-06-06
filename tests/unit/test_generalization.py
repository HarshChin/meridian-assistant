"""Generalization: NEVER-SEEN documents compile correctly with the SAME schema + prompt.

The proof the knowledge pipeline is not biased to the 13 sample PDFs. Two synthetic, unseen
service-area documents are extracted by the UNCHANGED coverage extractor:

* ``_GLYPH_DOC`` — the sample's garbled-table form ("3" = ✓ available, "7" = ✗ not available).
* ``_WORD_DOC`` — a DIFFERENT layout (pipe-delimited) with WORD-based availability
  (Yes / No / Pending / Sub-contracted) and a different partner — so the test cannot be passed
  by anything keyed to the "3"/"7" glyphs.

Both replay the committed LLM cache, so the suite runs keyless; nothing about the extractor,
schema, or prompts was specialised for either document.
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

# A fictional West region in the same garbled-table form a PDF extract produces
# ("3" = ✓ available, "7" = ✗ not available; explicit words win).
_GLYPH_DOC = """[source: service_area_west v1.0 — Covered ZIP Codes]
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

# A fictional East region with a DIFFERENT layout (pipe-delimited) and WORD-based availability,
# no "3"/"7" glyphs anywhere — proves the extractor generalises beyond the sample's encoding.
_WORD_DOC = """[source: service_area_east v1.0 — Coverage]
# Service Area — East Region

ZIP-code coverage for Calvert, Charles, and St. Mary's counties.
## Covered ZIP Codes
County | ZIP Codes | HVAC | Plumbing | Electrical
Calvert | 20610-20620 | Yes | Yes | No
Charles | 20630, 20640-20645 | Yes | Pending | Yes
St. Mary's | 20650 | Sub-contracted | Yes | Yes
## Notes
Electrical is not available in Calvert County; refer customers to partner GridWorks.
St. Mary's HVAC is sub-contracted, with no same-day service.
"""


def _extract(doc: str) -> ServiceAreaExtraction:
    return LLMClient().structured(_COVERAGE_SYSTEM, doc, ServiceAreaExtraction)


@pytest.fixture(scope="module")
def glyph() -> ServiceAreaExtraction:
    return _extract(_GLYPH_DOC)


@pytest.fixture(scope="module")
def words() -> ServiceAreaExtraction:
    return _extract(_WORD_DOC)


# ---------------------------------------------------------------- glyph-encoded unseen doc
def test_glyph_counties(glyph: ServiceAreaExtraction) -> None:
    assert {"shenandoah", "clarke", "warren"} <= {c.county.lower() for c in glyph.counties}


def test_glyph_tokens(glyph: ServiceAreaExtraction) -> None:
    by = {c.county.lower(): c for c in glyph.counties}
    assert by["shenandoah"].hvac == "available"  # "3" → ✓
    assert by["shenandoah"].electrical == "not_available"  # "7" → ✗
    assert by["clarke"].plumbing == "pending"
    assert by["warren"].hvac == "not_available"
    assert by["warren"].electrical == "subcontracted"


def test_glyph_zip_gap_preserved(glyph: ServiceAreaExtraction) -> None:
    segs = {c.county.lower(): c.zip_segments for c in glyph.counties}["shenandoah"]
    assert any(s.low <= 22812 <= s.high for s in segs)  # covered
    assert not any(s.low <= 22816 <= s.high for s in segs)  # gap between 22815 and 22820


def test_glyph_partner_and_coordination(glyph: ServiceAreaExtraction) -> None:
    by = {c.county.lower(): c for c in glyph.counties}
    assert (by["shenandoah"].refer_partner or "").lower().find("voltpro") >= 0
    assert 22640 in by["warren"].coordination_zips


def test_glyph_deterministic_decision(glyph: ServiceAreaExtraction) -> None:
    warren = next(c for c in glyph.counties if c.county.lower() == "warren")
    decision = _decide("22640", 22640, ServiceType.HVAC, warren, glyph)
    assert decision.eligibility is _TOKEN_TO_ELIGIBILITY["not_available"]
    assert decision.flags.coordination_required is True


# ---------------------------------------------------------- word-encoded, different layout
def test_word_counties(words: ServiceAreaExtraction) -> None:
    names = {c.county.lower() for c in words.counties}
    assert "calvert" in names and "charles" in names
    assert any("mary" in n for n in names)  # "St. Mary's"


def test_word_tokens(words: ServiceAreaExtraction) -> None:
    by = {c.county.lower(): c for c in words.counties}
    assert by["calvert"].hvac == "available"  # "Yes"
    assert by["calvert"].electrical == "not_available"  # "No"
    assert by["charles"].plumbing == "pending"  # "Pending"
    mary = next(c for c in words.counties if "mary" in c.county.lower())
    assert mary.hvac == "subcontracted"  # "Sub-contracted"


def test_word_zip_gap_preserved(words: ServiceAreaExtraction) -> None:
    segs = {c.county.lower(): c.zip_segments for c in words.counties}["charles"]
    assert any(s.low <= 20642 <= s.high for s in segs)  # covered (20640-20645)
    assert not any(s.low <= 20635 <= s.high for s in segs)  # gap between 20630 and 20640


def test_word_partner_referral(words: ServiceAreaExtraction) -> None:
    calvert = next(c for c in words.counties if c.county.lower() == "calvert")
    assert (calvert.refer_partner or "").lower().find("gridworks") >= 0
