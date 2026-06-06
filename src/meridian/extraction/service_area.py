"""Grounded service-area resolver: retrieve → LLM extracts structure → deterministic logic.

Replaces the hand-authored service-area YAML. The LLM extracts the coverage *structure*
from retrieved document chunks — generalising to any service-area document and robust to
PDF glyph artifacts (a check ``✓`` extracts as ``3``, a cross ``✗`` as ``7``). The precise,
booking-critical decisions (ZIP-range membership, eligibility, side-condition flags) then run
in deterministic code on the validated records, never by the LLM. Extractions are cached by
the :class:`~meridian.llm.client.LLMClient`, so the path is reproducible and runs keyless once
the cache is committed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.enums import CoverageEligibility, Region, ServiceType
from ..domain.service_area import CoverageDecision, CoverageFlags
from ..llm.client import LLMClient
from ..retrieval.retriever import HybridRetriever

# --------------------------------------------------------------------------------------
# Extraction schema — what the LLM emits from the retrieved chunks (document structure only).
# --------------------------------------------------------------------------------------


class ZipSegment(BaseModel):
    """An inclusive ZIP-code range; a single ZIP is encoded as ``low == high``."""

    low: int = Field(description="First 5-digit ZIP in the inclusive range.")
    high: int = Field(description="Last 5-digit ZIP in the range (equal to low if a single ZIP).")


class CountyCoverage(BaseModel):
    """Coverage for one county exactly as stated in the document."""

    county: str = Field(description="County (or city) name as written.")
    region: str | None = Field(
        default=None, description="north | central | south, from the document title if stated."
    )
    zip_segments: list[ZipSegment] = Field(description="Covered ZIP ranges; gaps preserved.")
    hvac: str = Field(description="available | pending | not_available | subcontracted")
    plumbing: str = Field(description="available | pending | not_available | subcontracted")
    electrical: str = Field(description="available | pending | not_available | subcontracted")
    primary_branch: str | None = Field(
        default=None, description="Primary branch if a branch table maps this county; else null."
    )
    overflow_branch: str | None = Field(
        default=None, description="Overflow branch; '—' means null."
    )
    same_day_blocked: bool = Field(
        default=False, description="True if the text says no same-day service for this county."
    )
    refer_partner: str | None = Field(
        default=None, description="Partner to refer to for an unavailable service (e.g. EcoPower)."
    )
    coordination_zips: list[int] = Field(
        default_factory=list, description="ZIPs the text says need facilities-office coordination."
    )


class ServiceAreaExtraction(BaseModel):
    """All county-coverage rows found in the retrieved service-area text."""

    counties: list[CountyCoverage] = Field(description="One entry per county row in the text.")
    out_of_area_policy: str | None = Field(
        default=None, description="What to do for unlisted ZIPs, if the text states it."
    )
    travel_surcharge_usd: int | None = Field(
        default=None, description="Travel-surcharge dollar amount if stated."
    )


_SYSTEM = """You extract service-area coverage from retrieved knowledge-base text for a \
home-services company. Return structured data describing each county's coverage EXACTLY as \
the text states it. Never invent counties, ZIPs, branches, or partners.

The text was extracted from PDFs and may contain glyph artifacts:
- A check mark (✓) commonly appears as the digit "3"  → treat as availability "available".
- A cross/x mark (✗) commonly appears as the digit "7" → treat as "not_available".
- Arrows or bullets may appear as "fi", "→", or stray characters — ignore them.
Explicit WORDS always take precedence over symbols: text containing "Pending" → "pending"; \
"Sub-contracted" → "subcontracted"; "not licensed" or "not available" → "not_available".

For each county row of a coverage table:
- Parse the ZIP column into integer inclusive [low, high] segments. A dash/en-dash range \
"22030–22039" → {low:22030, high:22039}. A comma-separated single ZIP "20832" → \
{low:20832, high:20832}. PRESERVE gaps — do not merge "22030–22039, 22041–22044" into one \
segment (the gap 22040 is genuinely not covered).
- Classify each of HVAC, Plumbing, Electrical as exactly one of: available, pending, \
not_available, subcontracted.
- Fill primary_branch / overflow_branch from a "Branch Assignments" table if one maps this \
county (an area row like "Fairfax / Arlington / Alexandria → Falls Church / Tysons" applies \
to each county it names). Use null when the document states no branch. An overflow of "—" is null.
- Set same_day_blocked=true if the text says same-day service is unavailable for the county.
- Set refer_partner to the named partner when a service is unavailable and the text says to \
refer customers elsewhere (e.g. "EcoPower").
- Put any ZIP the text says needs facilities-office coordination into coordination_zips.
Also capture the out-of-area policy and the travel-surcharge amount if stated. Extract only \
what the text supports."""

_RETRIEVAL_QUERY = (
    "service area coverage by county: ZIP code ranges, HVAC plumbing electrical availability, "
    "branch assignments, out-of-area policy, ZIP {zip}"
)

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


class ServiceAreaResolver:
    """Resolve ZIP + service → :class:`CoverageDecision` via grounded extraction + ZIP math."""

    def __init__(self, retriever: HybridRetriever, llm: LLMClient) -> None:
        """Initialise with a loaded retriever and an LLM client."""
        self._retriever = retriever
        self._llm = llm

    def check(self, zip_code: str, service_type: ServiceType) -> CoverageDecision:
        """Return the coverage decision for a ZIP + service line (grounded, document-faithful)."""
        zip_norm = zip_code.strip()
        if not (len(zip_norm) == 5 and zip_norm.isdigit()):
            return self._invalid(zip_code, service_type)

        zip_int = int(zip_norm)
        extraction, fallback_cite = self._extract(zip_norm)
        for county in extraction.counties:
            if any(seg.low <= zip_int <= seg.high for seg in county.zip_segments):
                return self._decide(
                    zip_norm, zip_int, service_type, county, extraction, fallback_cite
                )
        return self._unknown(zip_norm, service_type, fallback_cite)

    def _extract(self, zip_norm: str) -> tuple[ServiceAreaExtraction, str]:
        """Identify the relevant service-area document(s) and extract from their FULL text.

        Section-level cropping can drop side-conditions that live in a different section
        (e.g. an "Important Notes" partner-referral). So we rank *documents* by their
        retrieved chunks, then feed the complete top documents to the extractor — a
        parent-document pattern that is both more robust and corpus-agnostic. The document
        set is sorted deterministically, so the extraction prompt (and its cache key) is
        stable across ZIPs that map to the same documents.
        """
        results, _ = self._retriever.search(_RETRIEVAL_QUERY.format(zip=zip_norm), k=12)
        doc_scores: dict[str, float] = {}
        for rank, rc in enumerate(results):
            doc_scores[rc.chunk.doc_id] = doc_scores.get(rc.chunk.doc_id, 0.0) + 1.0 / (rank + 1)
        top_docs = sorted(sorted(doc_scores, key=lambda d: -doc_scores[d])[:2])
        chunks = [c for doc in top_docs for c in self._retriever.doc_chunks(doc)]
        context = "\n\n".join(f"[source: {c.citation()}]\n{c.text}" for c in chunks)
        fallback_cite = "; ".join(f"{doc} — service-area coverage" for doc in top_docs)
        extraction = self._llm.structured(_SYSTEM, context, ServiceAreaExtraction)
        return extraction, fallback_cite

    def _decide(
        self,
        zip_norm: str,
        zip_int: int,
        service_type: ServiceType,
        county: CountyCoverage,
        extraction: ServiceAreaExtraction,
        fallback_cite: str,
    ) -> CoverageDecision:
        """Map an extracted, matched county row to a :class:`CoverageDecision`."""
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
        if extraction.travel_surcharge_usd:
            flags.surcharge_possible = True

        region = self._region(county.region)
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
            citation=self._citation(region, fallback_cite),
            rationale=" ".join(notes) or f"{line} is available in {county.county}.",
        )

    def _unknown(
        self, zip_norm: str, service_type: ServiceType, fallback_cite: str
    ) -> CoverageDecision:
        """Build an UNKNOWN (escalate) decision for a ZIP in no documented segment."""
        return CoverageDecision(
            zip_code=zip_norm,
            service_type=service_type,
            eligibility=CoverageEligibility.UNKNOWN,
            source="none",
            citation=fallback_cite or "service-area coverage (ZIP not listed)",
            rationale=(
                "This ZIP is not in any documented service area. Per the out-of-area policy, "
                "escalate to the Branch Manager for spot-approval or confirm the address."
            ),
        )

    def _invalid(self, zip_code: str, service_type: ServiceType) -> CoverageDecision:
        """Build an UNKNOWN decision for a non 5-digit ZIP."""
        return CoverageDecision(
            zip_code=zip_code,
            service_type=service_type,
            eligibility=CoverageEligibility.UNKNOWN,
            source="none",
            citation="n/a",
            rationale="Not a valid 5-digit ZIP code; ask the customer to confirm it.",
        )

    @staticmethod
    def _region(region: str | None) -> Region | None:
        """Map an extracted region string to the :class:`Region` enum, if recognised."""
        if region and region.strip().lower() in Region.__members__.values():
            return Region(region.strip().lower())
        return None

    @staticmethod
    def _citation(region: Region | None, fallback_cite: str) -> str:
        """Prefer a region-specific document citation; fall back to retrieved chunk refs."""
        if region and region.value in _REGION_TO_DOC:
            return f"{_REGION_TO_DOC[region.value]} — Covered ZIP Codes"
        return fallback_cite or "service-area coverage"
