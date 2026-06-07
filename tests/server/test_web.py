"""Web-demo server tests (keyless): the HTTP layer maps turns and gates commits via /confirm.

A fake runner stands in for the real agent so these run without an index or API key. They assert
the two things the demo must get right: (1) a turn's message/citations/trace reach the browser,
and (2) a mutating booking is only resolved through the /confirm endpoint — the /messages endpoint
never commits.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from server.app import create_app

from meridian.agent import TurnResult
from meridian.llm.client import LLMUnavailableError
from meridian.tracing.trace import TurnTrace


class _FakeRunner:
    """Duck-typed stand-in for AgentRunner that records calls and returns canned results."""

    def __init__(self, on_message: TurnResult, on_confirm: TurnResult | None = None) -> None:
        self._on_message = on_message
        self._on_confirm = on_confirm
        self.confirm_calls: list[tuple[str, str]] = []
        self.message_calls: list[tuple[str, str]] = []

    def run_turn(self, session_id: str, message: str) -> TurnResult:
        self.message_calls.append((session_id, message))
        return self._on_message

    def confirm_turn(self, session_id: str, decision: str) -> TurnResult:
        self.confirm_calls.append((session_id, decision))
        assert self._on_confirm is not None
        return self._on_confirm


def _client(runner: _FakeRunner) -> TestClient:
    return TestClient(create_app(runner=runner))  # type: ignore[arg-type]


def test_knowledge_answer_returns_message_and_citations() -> None:
    trace = TurnTrace(channel="web_chat", route="answer", citations=["hvac_pricing#plans"])
    runner = _FakeRunner(TurnResult(kind="answer", message="Gold is $249.", trace=trace))
    resp = _client(runner).post("/api/sessions/s1/messages", json={"message": "plans?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "answer"
    assert body["message"] == "Gold is $249."
    assert body["citations"] == ["hvac_pricing#plans"]


def test_booking_requires_confirm_and_commits_only_via_confirm_endpoint() -> None:
    pending = TurnResult(
        kind="confirmation_required",
        message="Book HVAC at 22030?",
        preview="Book hvac at 22030.",
        proposed_action={"tool": "create_booking", "args": {"zip_code": "22030"}},
        trace=TurnTrace(channel="web_chat", route="confirm", confirmation_required=True),
    )
    committed = TurnResult(
        kind="answer",
        message="Booked! BK-00000001.",
        trace=TurnTrace(
            channel="web_chat", route="respond", committed=True, committed_booking_id="BK-00000001"
        ),
    )
    runner = _FakeRunner(on_message=pending, on_confirm=committed)
    client = _client(runner)

    # The proposing turn must NOT commit — it only asks for confirmation.
    first = client.post("/api/sessions/s2/messages", json={"message": "book hvac 22030"}).json()
    assert first["kind"] == "confirmation_required"
    assert first["proposed_action"]["tool"] == "create_booking"
    assert runner.confirm_calls == []  # nothing resumed/committed yet

    # The commit happens only when the user approves via /confirm.
    second = client.post("/api/sessions/s2/confirm", json={"decision": "approve"}).json()
    assert runner.confirm_calls == [("s2", "approve")]
    assert second["trace"]["committed"] is True
    assert second["trace"]["committed_booking_id"] == "BK-00000001"


def test_live_call_without_key_returns_503() -> None:
    class _NoKey(_FakeRunner):
        def run_turn(self, session_id: str, message: str) -> TurnResult:
            raise LLMUnavailableError("no key")

    runner = _NoKey(TurnResult(kind="answer", message=""))
    resp = _client(runner).post("/api/sessions/s3/messages", json={"message": "uncached"})
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["message"]
