"""Eval runner: drive each case through the real agent + retriever, score, render results.md.

Each case runs on a fresh in-process BookingService at the case's frozen clock, so the mutation
ledger is a clean per-case witness for the confirmation-gating invariant. Booking cases that pause
for confirmation are resumed with the case's ``confirm`` decision. The deterministic tier is
keyless (the agent's LLM calls replay from the committed cache).
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.seed import build_seed_store
from app.service import BookingService

from meridian.agent import AgentRunner
from meridian.clock import CANONICAL_NOW, FrozenClock
from meridian.domain.enums import Channel
from meridian.llm.client import LLMClient
from meridian.retrieval.retriever import HybridRetriever

from .dataset import EvalCase, load_cases
from .metrics import CaseResult, Report, RetrievalMetric, aggregate, render_results, score_case

_RESULTS_PATH = Path(__file__).resolve().parents[1] / "results.md"


def _case_now(case: EvalCase) -> datetime:
    return datetime.fromisoformat(case.now) if case.now else CANONICAL_NOW


def _run_one(case: EvalCase, llm: LLMClient, retriever: HybridRetriever) -> CaseResult:
    clock = FrozenClock(_case_now(case))
    service = BookingService(clock=clock, store=build_seed_store())
    runner = AgentRunner(llm, retriever, service, clock, Channel(case.channel))

    first = runner.run_turn(case.id, case.message)
    ledger_after_first = [m.op for m in service.store.mutations]  # the confirm-gating witness
    final = first
    if first.kind == "confirmation_required" and case.confirm:
        final = runner.confirm_turn(case.id, case.confirm)

    trace = final.trace.model_dump() if final.trace else {}
    ledger_final = [m.op for m in service.store.mutations]  # the emergency 'never book' witness
    return score_case(
        case,
        first_kind=first.kind,
        trace=trace,
        message=final.message,
        ledger_after_first=ledger_after_first,
        ledger_final=ledger_final,
    )


def _retrieval_metric(cases: list[EvalCase], retriever: HybridRetriever) -> RetrievalMetric:
    gold = [c for c in cases if c.retrieval_gold_doc]
    hits = 0
    reciprocal = 0.0
    for case in gold:
        docs = [r.chunk.doc_id for r in retriever.search(case.message)[0]]
        if case.retrieval_gold_doc in docs:
            hits += 1
            reciprocal += 1.0 / (docs.index(case.retrieval_gold_doc) + 1)
    n = len(gold)
    return RetrievalMetric(
        n=n, recall_at_5=hits / n if n else 0.0, mrr=reciprocal / n if n else 0.0
    )


def run_eval(write_results: bool = True) -> Report:
    """Run the deterministic eval tier and (optionally) write ``results.md``."""
    llm = LLMClient()
    retriever = HybridRetriever.load()
    cases = load_cases()
    scored = [(case, _run_one(case, llm, retriever)) for case in cases]
    report = aggregate(scored, _retrieval_metric(cases, retriever))
    if write_results:
        _RESULTS_PATH.write_text(render_results(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run the eval, print a summary, exit non-zero if a hard gate fails."""
    parser = argparse.ArgumentParser(description="Meridian evaluation harness.")
    parser.add_argument(
        "--tier",
        default="deterministic",
        choices=["deterministic", "judged"],
        help="deterministic (keyless CI gate) or judged (scaffolded; currently runs the "
        "deterministic tier — the LLM groundedness judge is not yet implemented).",
    )
    args = parser.parse_args(argv)
    report = run_eval()
    s = report.safety
    rec = report.retrieval
    print(f"cases: {report.passed}/{report.total} passed ({report.pass_rate * 100:.0f}%)")
    print(f"emergency recall: misses={s.emergency_misses}/{s.emergency_cases}")
    print(f"confirmation-gating: violations={s.gating_violations}/{s.gating_cases}")
    print(f"retrieval: recall@5={rec.recall_at_5 * 100:.0f}% MRR={rec.mrr:.2f}")
    if args.tier == "judged":
        print("(judged tier scaffolded; the deterministic tier is the CI gate.)")
    for result in report.results:
        if not result.passed:
            print(f"  FAIL {result.id}: {result.failures}")
    print("CI gate:", "PASS" if report.hard_gate_ok else "FAIL")
    return 0 if report.hard_gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
