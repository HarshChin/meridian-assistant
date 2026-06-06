"""The wired tools over the in-process service + compiled knowledge (needs the committed index)."""

from __future__ import annotations

import pytest
from app.seed import build_seed_store
from app.service import BookingService

from meridian.clock import CANONICAL_NOW, FrozenClock
from meridian.config import get_settings
from meridian.domain.errors import InvalidInputError, MutationOutsideCommitError
from meridian.retrieval.retriever import HybridRetriever
from meridian.tools import ToolRegistry, build_registry

pytestmark = pytest.mark.skipif(
    not (get_settings().index_dir / "chunks.jsonl").exists(),
    reason="retrieval index not built (run `make ingest`)",
)


@pytest.fixture(scope="module")
def retriever() -> HybridRetriever:
    return HybridRetriever.load()


@pytest.fixture
def registry(retriever: HybridRetriever) -> ToolRegistry:
    service = BookingService(clock=FrozenClock(CANONICAL_NOW), store=build_seed_store())
    return build_registry(retriever, service)


def test_full_surface_registered(registry: ToolRegistry) -> None:
    assert set(registry.names()) == {
        "knowledge_search",
        "check_service_area",
        "quote_fee",
        "lookup_booking",
        "escalate_to_human",
        "create_booking",
        "modify_booking",
    }
    assert {s["name"] for s in registry.specs(mutating=True)} == {
        "create_booking",
        "modify_booking",
    }


def test_create_booking_blocked_outside_commit(registry: ToolRegistry) -> None:
    args = {
        "customer_id": "CID-2000",
        "service_type": "hvac",
        "job_type": "tune_up",
        "zip_code": "22030",
        "preferred_date": "2026-01-28",
        "preferred_window": "morning",
    }
    with pytest.raises(MutationOutsideCommitError):
        registry.execute("create_booking", args, allow_mutations=False)


def test_check_service_area(registry: ToolRegistry) -> None:
    yes = registry.execute("check_service_area", {"zip_code": "22030", "service_type": "hvac"})
    assert yes.data["eligibility"] == "yes" and yes.data["primary_branch"] == "Falls Church"
    no = registry.execute("check_service_area", {"zip_code": "20147", "service_type": "electrical"})
    assert no.data["eligibility"] == "no"


def test_quote_fee_exact_amounts(registry: ToolRegistry) -> None:
    assert (
        registry.execute("quote_fee", {"kind": "diagnostic", "service_type": "hvac"}).data[
            "amount_usd"
        ]
        == 89
    )
    assert (
        registry.execute("quote_fee", {"kind": "emergency_dispatch", "service_type": "hvac"}).data[
            "amount_usd"
        ]
        == 89
    )
    assert (
        registry.execute("quote_fee", {"kind": "cancellation", "notice_hours": 25}).data[
            "amount_usd"
        ]
        == 0
    )
    assert (
        registry.execute("quote_fee", {"kind": "cancellation", "notice_hours": 1}).data[
            "amount_usd"
        ]
        == 75
    )
    # missing required field -> ok=False, not a crash
    assert registry.execute("quote_fee", {"kind": "diagnostic"}).ok is False


def test_lookup_booking_owner_and_not_found(registry: ToolRegistry) -> None:
    owned = registry.execute(
        "lookup_booking", {"booking_id": "BK-00391042", "customer_id": "CID-1001"}
    )
    assert owned.ok and owned.data["status"] == "confirmed" and owned.data["notes"] is not None
    missing = registry.execute("lookup_booking", {"booking_id": "BK-00000000"})
    assert missing.ok is False and missing.data["error"] == "not_found"


def test_create_then_runs_in_commit(registry: ToolRegistry) -> None:
    args = {
        "customer_id": "CID-2000",
        "service_type": "hvac",
        "job_type": "tune_up",
        "zip_code": "22030",
        "preferred_date": "2026-01-28",
        "preferred_window": "morning",
    }
    result = registry.execute("create_booking", args, allow_mutations=True)
    assert result.ok and result.data["status"] == "confirmed"


def test_modify_cancel_runs_in_commit(registry: ToolRegistry) -> None:
    result = registry.execute(
        "modify_booking", {"booking_id": "BK-00391042", "action": "cancel"}, allow_mutations=True
    )
    assert result.ok and result.data["status"] == "cancelled" and result.data["fee_applied"] == 0.0


def test_knowledge_search_returns_grounded_chunks(registry: ToolRegistry) -> None:
    result = registry.execute(
        "knowledge_search", {"query": "What is the no-show cancellation fee?"}
    )
    assert result.data["chunks"] and result.citations
    assert result.data["confidence"] in ("high", "medium")


def test_escalate_to_human(registry: ToolRegistry) -> None:
    result = registry.execute(
        "escalate_to_human", {"category": "emergency", "reason": "active gas smell"}
    )
    assert result.ok and result.data["category"] == "emergency"


def test_bad_tool_args_raise(registry: ToolRegistry) -> None:
    with pytest.raises(InvalidInputError):
        registry.execute("check_service_area", {"zip_code": "22030"})  # missing service_type
