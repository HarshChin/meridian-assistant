"""End-to-end agent tests over the LangGraph state machine (keyless via the committed LLM cache).

These assert the eval-relevant trace contract AND the mutation ledger — the strongest proof of
confirm-before-commit: no mutation is recorded until the customer approves the confirmation.
Skipped if the index / LLM cache are absent so the keyless gate still runs everywhere.
"""

from __future__ import annotations

import pytest
from app.seed import build_seed_store
from app.service import BookingService

from meridian.agent import AgentRunner
from meridian.clock import CANONICAL_NOW, FrozenClock
from meridian.config import get_settings
from meridian.llm.client import LLMClient
from meridian.retrieval.retriever import HybridRetriever

_SETTINGS = get_settings()
pytestmark = pytest.mark.skipif(
    not (_SETTINGS.index_dir / "chunks.jsonl").exists()
    or not any(_SETTINGS.llm_cache_dir.glob("*.json")),
    reason="needs the committed index + LLM cache (keyless replay)",
)


@pytest.fixture(scope="module")
def retriever() -> HybridRetriever:
    return HybridRetriever.load()


@pytest.fixture(scope="module")
def llm() -> LLMClient:
    return LLMClient()


def _runner(llm: LLMClient, retriever: HybridRetriever) -> tuple[AgentRunner, BookingService]:
    service = BookingService(clock=FrozenClock(CANONICAL_NOW), store=build_seed_store())
    return AgentRunner(llm, retriever, service, FrozenClock(CANONICAL_NOW)), service


def test_emergency_short_circuits_to_handoff(llm: LLMClient, retriever: HybridRetriever) -> None:
    runner, service = _runner(llm, retriever)
    res = runner.run_turn(
        "e1", "There's water actively leaking and flooding my basement right now!"
    )
    assert res.kind == "handoff"
    assert res.trace is not None and res.trace.emergency is True and res.trace.handoff is True
    assert res.trace.committed is False
    assert "1-800-555-0190" in res.message
    assert service.store.mutations == []  # never books on an emergency


def test_knowledge_answer_is_grounded(llm: LLMClient, retriever: HybridRetriever) -> None:
    runner, _ = _runner(llm, retriever)
    res = runner.run_turn("k1", "What is your no-show cancellation fee?")
    assert res.kind == "answer"
    assert res.trace is not None and res.trace.intent == "knowledge_qa"
    assert res.trace.citations  # cited
    assert "75" in res.message


def test_booking_confirms_then_commits_and_ledger_proves_order(
    llm: LLMClient, retriever: HybridRetriever
) -> None:
    runner, service = _runner(llm, retriever)
    step1 = runner.run_turn(
        "b1",
        "Book an HVAC tune-up at ZIP 22030 for 2026-01-28 in the morning. Customer id CID-5000.",
    )
    assert step1.kind == "confirmation_required"
    assert step1.trace is not None and step1.trace.committed is False
    # no mutating tool ran, and the ledger is empty BEFORE approval — confirm-before-commit
    assert all(c.capability != "mutating" for c in step1.trace.tool_calls)
    assert service.store.mutations == []

    step2 = runner.confirm_turn("b1", "approve")
    assert step2.trace is not None and step2.trace.committed is True
    assert (step2.trace.committed_booking_id or "").startswith("BK-")
    assert [m.op for m in service.store.mutations] == ["create"]  # exactly one, after approval
    # the trace SURVIVES the confirm interrupt: pre-confirm intent + the read-only coverage
    # check that proves confirm-before-commit are both present on the committed turn's trace.
    assert step2.trace.intent == "book"
    assert any(c.name == "check_service_area" for c in step2.trace.tool_calls)
    assert any(
        c.name == "create_booking" and c.capability == "mutating" for c in step2.trace.tool_calls
    )


def test_decline_leaves_ledger_empty(llm: LLMClient, retriever: HybridRetriever) -> None:
    runner, service = _runner(llm, retriever)
    runner.run_turn(
        "d1", "Book an HVAC tune-up at ZIP 22030 for 2026-01-28 morning. Customer CID-5002."
    )
    step2 = runner.confirm_turn("d1", "no")
    assert step2.trace is not None and step2.trace.committed is False
    assert service.store.mutations == []  # declined -> nothing changed


def test_out_of_area_does_not_confirm_or_commit(llm: LLMClient, retriever: HybridRetriever) -> None:
    runner, service = _runner(llm, retriever)
    res = runner.run_turn(
        "o1",
        "Book an electrical diagnostic at ZIP 20147 for 2026-01-28 morning. Customer CID-5001.",
    )
    assert res.kind == "answer"  # explained, not a confirmation
    assert res.trace is not None and res.trace.confirmation_required is False
    assert res.trace.committed is False
    assert service.store.mutations == []
    # coverage was actually checked (read-only) before declining
    assert any(c.name == "check_service_area" for c in res.trace.tool_calls)
