"""Service-area eligibility: ZIP → :class:`CoverageDecision`, from the COMPILED record.

The coverage record is extracted from the service-area documents at compile time
(:mod:`meridian.extraction`) and committed. This module applies deterministic ZIP-range
membership + eligibility/flag logic to it — **no LLM or retrieval at runtime**, so a retrieval
glitch can never change who we will or won't book. ZIP coverage is encoded as inclusive
``[low, high]`` segments, so gaps (e.g. 22040, 22210–22212) are correctly *not* covered.
"""

from __future__ import annotations

from ..domain.enums import CoverageEligibility, Region, ServiceType
from ..domain.service_area import CoverageDecision, CoverageFlags
from ..extraction.schemas import CountyCoverage, ServiceAreaExtraction
from .loader import load_coverage

_TOKEN_TO_ELIGIBILITY: dict[str, CoverageEligibility] = {
    "available": CoverageEligibility.YES,
    "pending": CoverageEligibility.PENDING,
    "not_available": CoverageEligibility.NO,
    "subcontracted": CoverageEligibility.YES,  # served, but flagged sub-contracted / no same-day
}

_REGION_TO_DOC: dict[str, str] = {
    "north": "service_area_north",
    "central": "service_area_central",
}


def check_coverage(zip_code: str, service_type: ServiceType) -> CoverageDecision:
    """Return the coverage decision for a ZIP + service line.

    Args:
        zip_code: A 5-digit US ZIP code (string).
        service_type: The requested service line.

    Returns:
        A fully-populated :class:`CoverageDecision`. ``eligibility`` is ``UNKNOWN`` for invalid
        ZIPs or ZIPs not in any documented segment (distinct from a documented ``NO``).
    """
    zip_norm = zip_code.strip()
    if not (len(zip_norm) == 5 and zip_norm.isdigit()):
        return _invalid(zip_code, service_type)

    zip_int = int(zip_norm)
    coverage = load_coverage()
    for county in coverage.counties:
        if any(seg.low <= zip_int <= seg.high for seg in county.zip_segments):
            return _decide(zip_norm, zip_int, service_type, county, coverage)
    return _unknown(zip_norm, service_type, coverage)


def _decide(
    zip_norm: str,
    zip_int: int,
    service_type: ServiceType,
    county: CountyCoverage,
    coverage: ServiceAreaExtraction,
) -> CoverageDecision:
    """Map a matched, compiled county row to a :class:`CoverageDecision`."""
    token = getattr(county, service_type.value).strip().lower()
    eligibility = _TOKEN_TO_ELIGIBILITY.get(token, CoverageEligibility.UNKNOWN)
    flags = CoverageFlags()
    notes: list[str] = []
    line = service_type.value.title()

    if token == "subcontracted":
        flags.sub_contracted = True
        flags.same_day_blocked = True
        notes.append(f"{line} is sub-contracted in {county.county}; no same-day service.")
    elif token == "pending":
        notes.append(f"{line} is pending in {county.county}.")
    elif token == "not_available":
        if county.refer_partner:
            flags.refer_partner = county.refer_partner
            notes.append(
                f"{line} is not available in {county.county}; refer to {county.refer_partner}."
            )
        else:
            notes.append(f"{line} is not available in {county.county}.")

    if county.same_day_blocked:
        flags.same_day_blocked = True
    if zip_int in county.coordination_zips:
        flags.coordination_required = True
        notes.append("Requires facilities-office coordination before booking.")
    if coverage.travel_surcharge_usd:
        flags.surcharge_possible = True

    region = _region(county.region)
    return CoverageDecision(
        zip_code=zip_norm,
        service_type=service_type,
        eligibility=eligibility,
        region=region,
        county=county.county,
        primary_branch=county.primary_branch,
        overflow_branch=county.overflow_branch,
        flags=flags,
        source="documented",
        confidence="high",
        citation=_citation(region),
        rationale=" ".join(notes) or f"{line} is available in {county.county}.",
    )


def _unknown(
    zip_norm: str, service_type: ServiceType, coverage: ServiceAreaExtraction
) -> CoverageDecision:
    """Build an UNKNOWN (escalate) decision for a ZIP in no documented segment."""
    docs = sorted(
        {_REGION_TO_DOC[c.region] for c in coverage.counties if c.region in _REGION_TO_DOC}
    )
    citation = f"{', '.join(docs)} (ZIP not listed)" if docs else "service-area coverage"
    return CoverageDecision(
        zip_code=zip_norm,
        service_type=service_type,
        eligibility=CoverageEligibility.UNKNOWN,
        source="none",
        citation=citation,
        rationale=(
            "This ZIP is not in any documented service area. Per the out-of-area policy, "
            "escalate to the Branch Manager for spot-approval or confirm the address."
        ),
    )


def _invalid(zip_code: str, service_type: ServiceType) -> CoverageDecision:
    """Build an UNKNOWN decision for a non 5-digit ZIP."""
    return CoverageDecision(
        zip_code=zip_code,
        service_type=service_type,
        eligibility=CoverageEligibility.UNKNOWN,
        source="none",
        citation="n/a",
        rationale="Not a valid 5-digit ZIP code; ask the customer to confirm it.",
    )


def _region(region: str | None) -> Region | None:
    """Map an extracted region string to the :class:`Region` enum, if recognised."""
    if region and region.strip().lower() in Region.__members__.values():
        return Region(region.strip().lower())
    return None


def _citation(region: Region | None) -> str:
    """Prefer a region-specific document citation."""
    if region and region.value in _REGION_TO_DOC:
        return f"{_REGION_TO_DOC[region.value]} — Covered ZIP Codes"
    return "service-area coverage"
