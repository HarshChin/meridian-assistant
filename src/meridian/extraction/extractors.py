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
from ..logging_setup import get_logger
from ..retrieval.retriever import HybridRetriever
from .schemas import BranchDirectory, FeeSchedule, ServiceAreaExtraction

_LOG = get_logger(__name__)

# Document selection is RELATIVE, never a fixed count, so the number of documents extracted
# scales with how many are genuinely relevant — no per-corpus constant, so adding documents
# needs no code change. A document is kept if EITHER signal fires:
#   (1) its aggregated chunk relevance reaches this fraction of the most-relevant document's, OR
_DOC_RELEVANCE_RATIO = 0.5
#   (2) it has a single chunk this strongly on-topic (dense cosine) — this catches a
#       strong-but-singular match (e.g. one fee stated in an FAQ) that a higher-volume document
#       would otherwise mask in the aggregate. Calibrated above the observed noise ceiling.
_STRONG_COSINE = 0.75
# Generous candidate pool so a relevant document is never buried below the cut by corpus size.
_CANDIDATE_CHUNKS = 30
# Safety bound on a single extraction's context (logged, not silent). Beyond this, shard the
# capability per entity (as fees do per service line) rather than widening one call.
_MAX_DOCS = 12


def _gather(retriever: HybridRetriever, query: str) -> tuple[str, list[str]]:
    """Select the documents relevant to ``query`` (relative score OR strong match) + full text.

    Retrieves a generous candidate pool, then keeps a document if its aggregated chunk relevance
    is within :data:`_DOC_RELEVANCE_RATIO` of the most relevant document OR it has a chunk at or
    above :data:`_STRONG_COSINE` — never a fixed top-N. Documents are sorted deterministically so
    the extraction prompt (and its LLM cache key) is stable across runs.
    """
    results, _ = retriever.search(query, k=_CANDIDATE_CHUNKS, candidate_k=_CANDIDATE_CHUNKS)
    aggregate: dict[str, float] = {}
    best_cosine: dict[str, float] = {}
    for rank, rc in enumerate(results):
        doc = rc.chunk.doc_id
        aggregate[doc] = aggregate.get(doc, 0.0) + 1.0 / (rank + 1)
        best_cosine[doc] = max(best_cosine.get(doc, 0.0), rc.dense_cosine)
    if not aggregate:
        return "", []
    cutoff = _DOC_RELEVANCE_RATIO * max(aggregate.values())
    ranked = sorted(aggregate, key=lambda d: (-aggregate[d], d))
    kept = [d for d in ranked if aggregate[d] >= cutoff or best_cosine[d] >= _STRONG_COSINE]
    if len(kept) > _MAX_DOCS:
        _LOG.warning("extraction.doc_cap_hit", query=query, relevant=len(kept), cap=_MAX_DOCS)
        kept = kept[:_MAX_DOCS]
    docs = sorted(kept)
    chunks = [c for doc in docs for c in retriever.doc_chunks(doc)]
    context = "\n\n".join(f"[source: {c.citation()}]\n{c.text}" for c in chunks)
    return context, docs


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

Availability cells may use WORDS or SYMBOLS, and PDF extraction often garbles symbols:
- An affirmative mark (a check "✓") may extract as "3", "Y", "P", or similar → "available".
- A negative mark (a cross "✗"/"X") may extract as "7", "N", or an empty cell → "not_available".
- Stray characters such as "fi", "→", or bullets are extraction noise — ignore them.
Explicit WORDS always take precedence over symbols: "Available"/"Yes" → "available"; "Not \
available"/"No"/"not licensed" → "not_available"; "Pending" → "pending"; "Sub-contracted" → \
"subcontracted".

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
    context, docs = _gather(retriever, _COVERAGE_QUERY)
    return llm.structured(_COVERAGE_SYSTEM, context, ServiceAreaExtraction), docs


# --------------------------------------------------------------------------------------
# Fee schedule
# --------------------------------------------------------------------------------------


class _CancellationFees(BaseModel):
    """Cancellation / no-show fee values (from the cancellation policy document)."""

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


class _SurchargeFees(BaseModel):
    """After-hours / Sunday-holiday surcharge values (from the pricing document)."""

    weekday_after_hours_usd: int = Field(
        description="Surcharge for Mon-Sat calls before opening or at/after closing."
    )
    sunday_holiday_usd: int = Field(description="Sunday / federal-holiday surcharge in USD.")
    business_hours_start_hour: int = Field(description="Hour (0-23) business hours begin.")
    business_hours_end_hour: int = Field(description="Hour (0-23) business hours end.")


class _DiagnosticFee(BaseModel):
    """The flat diagnostic / service-call fee for one service line."""

    fee_usd: int = Field(
        description="Flat 'Diagnostic Fee' or 'Service Call Fee' amount for this line, in USD."
    )


class _EmergencyDispatchFees(BaseModel):
    """Per-service-line emergency dispatch fees (often stated together in one document)."""

    fees_usd: dict[str, int] = Field(
        description="Map of service line (lowercase: hvac/plumbing/electrical) -> emergency "
        "dispatch fee in USD, for EACH line the text explicitly gives one. Omit any line with "
        "no stated emergency dispatch fee. A diagnostic/service-call fee is NOT one.",
    )


_CANCELLATION_QUERY = (
    "cancellation and no-show fees, notice-period thresholds, once-per-period no-show waiver, "
    "rescheduling fees"
)

_CANCELLATION_SYSTEM = """Extract a home-services company's CANCELLATION fee schedule from \
retrieved policy text. Extract only values the text states.

- free_notice_hours: notice threshold above which a cancellation is free \
("more than 24 hours" → 24).
- late_cancel_threshold_hours: lower notice bound of the late-cancel band ("2 to 24 hours" → 2).
- late_cancel_fee_usd / no_show_fee_usd: the two cancellation fee amounts.
- no_show_waiver_period_months: the once-per-period waiver length \
("once per 12-month period" → 12)."""

_SURCHARGE_QUERY = (
    "after-hours surcharge, Sunday and federal-holiday surcharge, business opening and closing "
    "hours, calls before 7 am or after 6 pm"
)

_SURCHARGE_SYSTEM = """Extract a home-services company's after-hours / Sunday-holiday SURCHARGE \
schedule from retrieved pricing text. Extract only values the text states.

- weekday_after_hours_usd: Mon-Sat before-open / after-close surcharge ("+$75 before 7 am or \
after 6 pm" → 75).
- sunday_holiday_usd: Sunday / federal-holiday surcharge \
("+$125 on Sundays and federal holidays" → 125).
- business_hours_start_hour / business_hours_end_hour: 24-hour bounds implied by the surcharge \
text ("before 7 am or after 6 pm" → start 7, end 18)."""

_DIAGNOSTIC_QUERY = "{line} diagnostic fee, {line} service call fee, flat fee amount"

_DIAGNOSTIC_SYSTEM = """Extract the flat diagnostic or service-call fee for the {line} service \
line from retrieved pricing text. Treat "Diagnostic Fee" and "Service Call Fee" as the same \
concept and return {line}'s amount only. Ignore other service lines and ignore emergency \
dispatch fees."""

_EMERGENCY_QUERY = (
    "emergency dispatch fee, emergency service dispatch, active water leak emergency, "
    "after-hours emergency dispatch fees per service line plumbing HVAC"
)

_EMERGENCY_SYSTEM = """Extract EMERGENCY DISPATCH fees per service line from retrieved text. \
Some documents state them together, e.g. "Emergency dispatch fees ($99 plumbing, $89 HVAC)". \
Return fees_usd as a map of service line -> dollar amount for EVERY line the text explicitly \
gives an emergency dispatch fee (lowercase keys: hvac, plumbing, electrical). A diagnostic or \
service-call fee is NOT an emergency dispatch fee — do not include it. Omit any line with no \
stated emergency dispatch fee."""


def extract_fees(retriever: HybridRetriever, llm: LLMClient) -> tuple[FeeSchedule, list[str]]:
    """Compile the fee schedule: one company-wide extraction + one per service line.

    Per-line fees (diagnostic, emergency dispatch) are compiled by iterating the known service
    lines with a targeted retrieval each, so completeness does not depend on every pricing
    document ranking in a single top-N — this is what lets it scale to many pricing documents.
    Each fee concept is extracted from its own targeted retrieval (cancellation, surcharge, and
    one per service line) rather than one broad query — so completeness never depends on several
    differently-relevant documents all surfacing in a single top-N. An emergency-dispatch fee may
    live in a different document than the line's pricing sheet (e.g. the emergencies FAQ), which
    the relevance-gated selection picks up.
    """
    used_docs: set[str] = set()

    cancel_ctx, docs = _gather(retriever, _CANCELLATION_QUERY)
    used_docs.update(docs)
    cancellation = llm.structured(_CANCELLATION_SYSTEM, cancel_ctx, _CancellationFees)

    surcharge_ctx, docs = _gather(retriever, _SURCHARGE_QUERY)
    used_docs.update(docs)
    surcharge = llm.structured(_SURCHARGE_SYSTEM, surcharge_ctx, _SurchargeFees)

    diagnostic: dict[str, int] = {}
    for line in ServiceType:
        ctx, docs = _gather(retriever, _DIAGNOSTIC_QUERY.format(line=line.value))
        used_docs.update(docs)
        diagnostic[line.value] = llm.structured(
            _DIAGNOSTIC_SYSTEM.format(line=line.value), ctx, _DiagnosticFee
        ).fee_usd

    emer_ctx, docs = _gather(retriever, _EMERGENCY_QUERY)
    used_docs.update(docs)
    emergency_raw = llm.structured(_EMERGENCY_SYSTEM, emer_ctx, _EmergencyDispatchFees).fees_usd
    emergency = {k.lower(): v for k, v in emergency_raw.items()}

    fees = FeeSchedule(
        **cancellation.model_dump(),
        **surcharge.model_dump(),
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
    context, docs = _gather(retriever, _BRANCH_QUERY)
    return llm.structured(_BRANCH_SYSTEM, context, BranchDirectory), docs
