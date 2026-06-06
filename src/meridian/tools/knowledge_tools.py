"""Read-only knowledge tools: grounded search, service-area check, and exact fee quotes.

All three are non-mutating. ``knowledge_search`` returns retrieved chunks + citations for the
agent to answer from (RAG); ``check_service_area`` and ``quote_fee`` run the deterministic logic
over the compiled records so the numbers are exact rather than guessed.
"""

from __future__ import annotations

from ..domain.enums import JobType
from ..knowledge.coverage import check_coverage
from ..knowledge.fees import after_hours_surcharge, cancellation_fee, diagnostic_fee
from ..knowledge.loader import fee_source_docs, load_fees
from ..retrieval.confidence import Confidence
from ..retrieval.retriever import HybridRetriever
from .base import ToolResult
from .schemas import CheckServiceAreaArgs, KnowledgeSearchArgs, QuoteFeeArgs


def knowledge_search(retriever: HybridRetriever, args: KnowledgeSearchArgs) -> ToolResult:
    """Retrieve grounding chunks for a question; surfaces retrieval confidence for abstention."""
    results, confidence = retriever.search(args.query)
    chunks = [{"citation": r.chunk.citation(), "text": r.chunk.text} for r in results]
    return ToolResult(
        tool="knowledge_search",
        ok=confidence is not Confidence.LOW,
        summary=f"Retrieved {len(chunks)} chunk(s); retrieval confidence {confidence.value}.",
        data={"confidence": confidence.value, "chunks": chunks},
        citations=[r.chunk.citation() for r in results],
    )


def check_service_area(args: CheckServiceAreaArgs) -> ToolResult:
    """Return the documented service-area decision for a ZIP + service line."""
    decision = check_coverage(args.zip_code, args.service_type)
    return ToolResult(
        tool="check_service_area",
        ok=True,
        summary=decision.rationale,
        data=decision.model_dump(mode="json"),
        citations=[decision.citation],
    )


def _missing(kind: str, field: str) -> ToolResult:
    return ToolResult(
        tool="quote_fee",
        ok=False,
        summary=f"A '{kind}' quote needs '{field}'.",
        data={"kind": kind},
    )


def quote_fee(args: QuoteFeeArgs) -> ToolResult:
    """Compute an exact fee (diagnostic / emergency dispatch / cancellation / after-hours)."""
    if args.kind == "diagnostic":
        if args.service_type is None:
            return _missing(args.kind, "service_type")
        amount = diagnostic_fee(
            args.service_type,
            args.job_type or JobType.DIAGNOSTIC,
            same_day_repair_booked=args.same_day_repair_booked,
        )
    elif args.kind == "emergency_dispatch":
        if args.service_type is None:
            return _missing(args.kind, "service_type")
        documented = load_fees().emergency_dispatch_fees_usd
        # Distinguish "documented as free" from "not documented" — never quote an ungrounded $0.
        if args.service_type.value not in documented:
            return ToolResult(
                tool="quote_fee",
                ok=False,
                summary=f"No emergency dispatch fee is documented for {args.service_type.value}.",
                data={"kind": "emergency_dispatch", "service_type": args.service_type.value},
            )
        amount = documented[args.service_type.value]
    elif args.kind == "cancellation":
        if args.notice_hours is None:
            return _missing(args.kind, "notice_hours")
        amount = cancellation_fee(args.notice_hours)
    else:  # after_hours_surcharge
        if args.appointment_datetime is None:
            return _missing(args.kind, "appointment_datetime")
        amount = after_hours_surcharge(args.appointment_datetime)
    return ToolResult(
        tool="quote_fee",
        ok=True,
        summary=f"{args.kind} fee: ${amount}.",
        data={"kind": args.kind, "amount_usd": amount},
        citations=fee_source_docs(),
    )
