"""Compile-time grounded extractors: retrieve relevant docs → LLM extracts a capability record.

Each extractor uses the **parent-document** pattern — rank documents by their retrieved
chunks, then extract from the FULL text of the top documents — so a fact in any section
(an "Important Notes" referral, an "After-Hours Surcharge" line) is never cropped out. This
is pure compile-time work; runtime loads the materialised records and never calls the LLM.

Robustness to PDF glyph artifacts (a check ``✓`` extracts as ``3``, a cross ``✗`` as ``7``,
arrows as ``fi``) is handled in the prompts, not by per-document hacks — so the extractors
generalise to documents they have never seen.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.enums import ServiceType
from ..llm.client import LLMClient
from ..retrieval.retriever import HybridRetriever
from .schemas import BranchDirectory, FeeSchedule, ServiceAreaExtraction


def _gather_top_docs(retriever: HybridRetriever, query: str, n_docs: int) -> tuple[str, list[str]]:
    """Rank documents by their retrieved chunks; return (full-text context, doc ids).

    The document set is sorted deterministically so the extraction prompt — and therefore the
    LLM cache key — is stable across runs.
    """
    results, _ = retriever.search(query, k=max(12, n_docs * 4))
    doc_scores: dict[str, float] = {}
    for rank, rc in enumerate(results):
        doc_scores[rc.chunk.doc_id] = doc_scores.get(rc.chunk.doc_id, 0.0) + 1.0 / (rank + 1)
    top_docs = sorted(sorted(doc_scores, key=lambda d: -doc_scores[d])[:n_docs])
    chunks = [c for doc in top_docs for c in retriever.doc_chunks(doc)]
    context = "\n\n".join(f"[source: {c.citation()}]\n{c.text}" for c in chunks)
    return context, top_docs


# --------------------------------------------------------------------------------------
# Service-area coverage
# --------------------------------------------------------------------------------------

_COVERAGE_QUERY = (
    "service area coverage by county: ZIP code ranges, HVAC plumbing electrical availability, "
    "branch assignments, out-of-area policy"
)

_COVERAGE_SYSTEM = """You extract service-area coverage from retrieved knowledge-base text for a \
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


def extract_coverage(
    retriever: HybridRetriever, llm: LLMClient
) -> tuple[ServiceAreaExtraction, list[str]]:
    """Extract the service-area coverage record from the corpus."""
    context, docs = _gather_top_docs(retriever, _COVERAGE_QUERY, 2)
    return llm.structured(_COVERAGE_SYSTEM, context, ServiceAreaExtraction), docs


# --------------------------------------------------------------------------------------
# Fee schedule
# --------------------------------------------------------------------------------------


class _CoreFees(BaseModel):
    """Company-wide cancellation + surcharge values (not per service line)."""

    free_notice_hours: int = Field(
        description="Cancellations with MORE notice than this many hours incur no fee."
    )
    late_cancel_threshold_hours: int = Field(
        description="Lower notice bound (hours) of the late-cancel band; below it (or a "
        "no-show) the no-show fee applies."
    )
    late_cancel_fee_usd: int = Field(description="Late-cancellation fee in USD.")
    no_show_fee_usd: int = Field(description="No-show fee in USD.")
    no_show_waiver_period_months: int = Field(
        description="The no-show fee is waived once per this many months per customer."
    )
    weekday_after_hours_usd: int = Field(
        description="Surcharge for Mon-Sat calls before opening or at/after closing."
    )
    sunday_holiday_usd: int = Field(description="Sunday / federal-holiday surcharge in USD.")
    business_hours_start_hour: int = Field(description="Hour (0-23) business hours begin.")
    business_hours_end_hour: int = Field(description="Hour (0-23) business hours end.")


class _LineFees(BaseModel):
    """Per-service-line fees, extracted one line at a time from that line's pricing text."""

    diagnostic_fee_usd: int = Field(
        description="Flat diagnostic or service-call fee for this service line, in USD."
    )
    emergency_dispatch_fee_usd: int | None = Field(
        default=None,
        description="Emergency dispatch fee for this line ONLY if the text explicitly states "
        "one for emergency/active-leak calls; otherwise null. A diagnostic or service-call "
        "fee is NOT one.",
    )


_CORE_FEE_QUERY = (
    "cancellation and no-show fees, notice period and once-per-period waiver, after-hours and "
    "Sunday or federal-holiday surcharge, business opening and closing hours"
)

_CORE_FEE_SYSTEM = """You compile a home-services company's company-wide cancellation and \
surcharge fees from retrieved policy/pricing text. Extract only values the text states.

- free_notice_hours: notice threshold above which a cancellation is free \
("more than 24 hours" → 24).
- late_cancel_threshold_hours: lower notice bound of the late-cancel band ("2 to 24 hours" → 2).
- late_cancel_fee_usd / no_show_fee_usd: the two cancellation fee amounts.
- no_show_waiver_period_months: the once-per-period waiver length ("once per 12-month period" → 12).
- weekday_after_hours_usd: Mon-Sat before-open / after-close surcharge ("+$75 before 7 am or \
after 6 pm" → 75).
- sunday_holiday_usd: Sunday / federal-holiday surcharge \
("+$125 on Sundays and federal holidays" → 125).
- business_hours_start_hour / business_hours_end_hour: 24-hour bounds implied by the surcharge \
text ("before 7 am or after 6 pm" → start 7, end 18)."""

_LINE_FEE_QUERY = "{line} diagnostic fee, {line} service call fee, {line} emergency dispatch fee"

_LINE_FEE_SYSTEM = """You extract fees for the {line} service line from retrieved pricing text.

- diagnostic_fee_usd: the flat "Diagnostic Fee" or "Service Call Fee" amount for {line} (treat \
the two terms as the same concept).
- emergency_dispatch_fee_usd: set this ONLY if the text explicitly states an "emergency dispatch \
fee" for {line} (e.g. for active water leaks / emergency calls); otherwise null. A diagnostic or \
service-call fee is NOT an emergency dispatch fee.
Extract {line}'s values only — ignore other service lines that may appear in the text."""


def extract_fees(retriever: HybridRetriever, llm: LLMClient) -> tuple[FeeSchedule, list[str]]:
    """Compile the fee schedule: one company-wide extraction + one per service line.

    Per-line fees (diagnostic, emergency dispatch) are compiled by iterating the known service
    lines with a targeted retrieval each, so completeness does not depend on every pricing
    document ranking in a single top-N — this is what lets it scale to many pricing documents.
    """
    core_ctx, core_docs = _gather_top_docs(retriever, _CORE_FEE_QUERY, 2)
    core = llm.structured(_CORE_FEE_SYSTEM, core_ctx, _CoreFees)

    diagnostic: dict[str, int] = {}
    emergency: dict[str, int] = {}
    used_docs = set(core_docs)
    for line in ServiceType:
        ctx, docs = _gather_top_docs(retriever, _LINE_FEE_QUERY.format(line=line.value), 2)
        used_docs.update(docs)
        line_fees = llm.structured(_LINE_FEE_SYSTEM.format(line=line.value), ctx, _LineFees)
        diagnostic[line.value] = line_fees.diagnostic_fee_usd
        if line_fees.emergency_dispatch_fee_usd is not None:
            emergency[line.value] = line_fees.emergency_dispatch_fee_usd

    fees = FeeSchedule(
        **core.model_dump(),
        diagnostic_fees_usd=diagnostic,
        emergency_dispatch_fees_usd=emergency,
    )
    return fees, sorted(used_docs)


# --------------------------------------------------------------------------------------
# Branch directory
# --------------------------------------------------------------------------------------

_BRANCH_QUERY = (
    "branch operating hours by location and day, Monday to Friday Saturday Sunday hours, "
    "contact center hours, 24/7 emergency phone line"
)

_BRANCH_SYSTEM = """You extract a home-services company's BRANCH DIRECTORY from retrieved text. \
Return one entry per branch LOCATION (not the contact center) with its region and its \
Mon-Fri, Saturday, and Sunday hours.

Normalise each day's hours to a 24-hour range "HH:MM-HH:MM" (e.g. "7 am – 6 pm" → "07:00-18:00", \
"8 am – 2 pm" → "08:00-14:00"). If a day shows "Closed" use "closed"; if it shows "Emergency" \
(emergency line only) use "emergency". Capture the 24/7 emergency phone number exactly as \
written. Extract only branches the text lists."""


def extract_branches(
    retriever: HybridRetriever, llm: LLMClient
) -> tuple[BranchDirectory, list[str]]:
    """Extract the branch directory + emergency line from the corpus."""
    context, docs = _gather_top_docs(retriever, _BRANCH_QUERY, 2)
    return llm.structured(_BRANCH_SYSTEM, context, BranchDirectory), docs
