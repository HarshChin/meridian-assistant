"""Service-area eligibility: ZIP → :class:`CoverageDecision`, from curated YAML.

This is booking-critical logic, so it reads the **hand-verified YAML** (not the RAG
index): a retrieval glitch must never change who we will or won't book. ZIP coverage
is encoded as inclusive ``[low, high]`` segments, so gaps (e.g. 22040, 22210–22212)
are correctly *not* covered. Resolution order: documented county ranges → inferred
branch-city overrides (low confidence) → ``UNKNOWN`` (escalate). Documented ranges are
never silently widened.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings
from ..domain.enums import CoverageEligibility, Region, ServiceType
from ..domain.service_area import CoverageDecision, CoverageFlags

_TOKEN_TO_ELIGIBILITY: dict[str, CoverageEligibility] = {
    "covered": CoverageEligibility.YES,
    "pending": CoverageEligibility.PENDING,
    "unavailable": CoverageEligibility.NO,
    "subcontracted": CoverageEligibility.YES,  # served, but with side-condition flags
}


def _service_area_dir() -> Path:
    """Return the directory holding the service-area YAML files."""
    return get_settings().data_dir / "service_area"


@functools.lru_cache(maxsize=1)
def _load_regions() -> list[dict[str, Any]]:
    """Load and cache the documented region YAML files (north, central)."""
    docs: list[dict[str, Any]] = []
    for name in ("north.yaml", "central.yaml"):
        path = _service_area_dir() / name
        docs.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return docs


@functools.lru_cache(maxsize=1)
def _load_overrides() -> dict[str, Any]:
    """Load and cache the inferred branch-city overrides."""
    path = _service_area_dir() / "overrides.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _zip_in_segments(zip_int: int, segments: list[list[int]]) -> bool:
    """Return True if ``zip_int`` falls within any inclusive ``[lo, hi]`` segment."""
    return any(lo <= zip_int <= hi for lo, hi in segments)


def check_coverage(zip_code: str, service_type: ServiceType) -> CoverageDecision:
    """Return the coverage decision for a ZIP + service type.

    Args:
        zip_code: A 5-digit US ZIP code (string).
        service_type: The requested service line.

    Returns:
        A fully-populated :class:`CoverageDecision`. ``eligibility`` is ``UNKNOWN`` for
        invalid ZIPs or ZIPs not in any documented area or override.
    """
    zip_norm = zip_code.strip()
    if not (len(zip_norm) == 5 and zip_norm.isdigit()):
        return CoverageDecision(
            zip_code=zip_code,
            service_type=service_type,
            eligibility=CoverageEligibility.UNKNOWN,
            source="none",
            citation="n/a",
            rationale="Not a valid 5-digit ZIP code; ask the customer to confirm it.",
        )

    zip_int = int(zip_norm)

    for region_doc in _load_regions():
        for county in region_doc["counties"]:
            if _zip_in_segments(zip_int, county["zips"]):
                return _decide_from_county(zip_norm, service_type, region_doc, county)

    for entry in _load_overrides().get("zips", []):
        if entry["zip"] == zip_norm:
            return _decide_from_override(zip_norm, service_type, _load_overrides(), entry)

    return CoverageDecision(
        zip_code=zip_norm,
        service_type=service_type,
        eligibility=CoverageEligibility.UNKNOWN,
        source="none",
        citation="service_area_north / service_area_central (ZIP not listed)",
        rationale=(
            "This ZIP is not in any documented service area. Offer Branch-Manager "
            "spot-approval or confirm the service address."
        ),
    )


def _decide_from_county(
    zip_norm: str,
    service_type: ServiceType,
    region_doc: dict[str, Any],
    county: dict[str, Any],
) -> CoverageDecision:
    """Build a documented-coverage decision for a matched county."""
    token = county["services"][service_type.value]
    eligibility = _TOKEN_TO_ELIGIBILITY[token]
    flags = CoverageFlags()
    notes: list[str] = []

    if token == "subcontracted":
        flags.sub_contracted = True
        flags.same_day_blocked = True
        notes.append(county.get("subcontracted_note", "Sub-contracted; no same-day service."))
    elif token == "pending":
        notes.append(county.get("pending_note", "This service is pending in this area."))
    elif token == "unavailable":
        partner = (
            county.get("electrical_refer_partner")
            if service_type is ServiceType.ELECTRICAL
            else None
        )
        if partner:
            flags.refer_partner = partner
            notes.append(county.get("electrical_note", f"Not available; refer to {partner}."))
        else:
            notes.append("This service is not available in this area.")

    if int(zip_norm) in county.get("coordination_flag_zips", []):
        flags.coordination_required = True
        notes.append(county.get("coordination_note", "Requires facilities coordination."))

    if region_doc.get("travel_surcharge_usd"):
        flags.surcharge_possible = True

    rationale = " ".join(notes) or f"{service_type.value} is available in {county['name']}."
    return CoverageDecision(
        zip_code=zip_norm,
        service_type=service_type,
        eligibility=eligibility,
        region=Region(region_doc["region"]),
        county=county["name"],
        primary_branch=county.get("primary_branch"),
        overflow_branch=county.get("overflow_branch"),
        flags=flags,
        source="documented",
        confidence="high",
        citation=f"{region_doc['doc_id']} v{region_doc['version']} — {county['name']}",
        rationale=rationale,
    )


def _decide_from_override(
    zip_norm: str,
    service_type: ServiceType,
    overrides: dict[str, Any],
    entry: dict[str, Any],
) -> CoverageDecision:
    """Build a low-confidence decision from an inferred branch-city override."""
    token = entry["services"][service_type.value]
    return CoverageDecision(
        zip_code=zip_norm,
        service_type=service_type,
        eligibility=_TOKEN_TO_ELIGIBILITY[token],
        region=Region(entry["region"]),
        county=entry.get("county"),
        primary_branch=entry.get("primary_branch"),
        overflow_branch=entry.get("overflow_branch"),
        flags=CoverageFlags(surcharge_possible=True),
        source="override",
        confidence=str(overrides.get("confidence", "low")),
        citation=f"override ({overrides.get('source')})",
        rationale=(
            "This ZIP is not in the documented ranges but matches a Meridian branch "
            "city, so coverage is inferred (low confidence) — confirm with the customer."
        ),
    )
