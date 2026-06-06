"""Keyless tests for the CLI turn-loop + rendering (a stub runner — no LLM, no index)."""

from __future__ import annotations

import io

from meridian.agent import TurnResult
from meridian.cli import _trace_summary, handle_turn, run_demo
from meridian.tracing.trace import ToolCallTrace, TurnTrace


class StubRunner:
    """Duck-typed AgentRunner returning canned results and recording the calls made."""

    def __init__(
        self, run_results: list[TurnResult], confirm_results: list[TurnResult] | None = None
    ) -> None:
        self._run = list(run_results)
        self._confirm = list(confirm_results or [])
        self.run_calls: list[tuple[str, str]] = []
        self.confirm_calls: list[tuple[str, str]] = []

    def run_turn(self, session_id: str, message: str) -> TurnResult:
        self.run_calls.append((session_id, message))
        return self._run.pop(0)

    def confirm_turn(self, session_id: str, decision: str) -> TurnResult:
        self.confirm_calls.append((session_id, decision))
        return self._confirm.pop(0)


def _answer(message: str, citations: list[str] | None = None) -> TurnResult:
    trace = TurnTrace(channel="agent", route="answer", citations=citations or [])
    return TurnResult(kind="answer", message=message, trace=trace)


def _confirm(preview: str) -> TurnResult:
    return TurnResult(
        kind="confirmation_required",
        message="please confirm",
        preview=preview,
        trace=TurnTrace(channel="agent"),
    )


def test_answer_renders_message_and_sources() -> None:
    runner = StubRunner([_answer("The no-show fee is $75.", ["cancellation_policy v2.0"])])
    out = io.StringIO()
    result = handle_turn(runner, "s", "fee?", decide=lambda _r: "approve", out=out)
    assert result.kind == "answer"
    assert "The no-show fee is $75." in out.getvalue()
    assert "cancellation_policy v2.0" in out.getvalue()
    assert runner.confirm_calls == []  # no confirmation prompted for a plain answer


def test_confirmation_loop_passes_decision_then_renders_result() -> None:
    runner = StubRunner([_confirm("Book hvac at 22030")], [_answer("Booked BK-1!")])
    out = io.StringIO()
    result = handle_turn(runner, "s", "book it", decide=lambda _r: "approve", out=out)
    assert runner.confirm_calls == [("s", "approve")]
    assert result.message == "Booked BK-1!"
    assert "Booked BK-1!" in out.getvalue()


def test_decline_is_forwarded() -> None:
    runner = StubRunner([_confirm("Cancel BK-1")], [_answer("Nothing was changed.")])
    out = io.StringIO()
    handle_turn(runner, "s", "cancel", decide=lambda _r: "decline", out=out)
    assert runner.confirm_calls == [("s", "decline")]


def test_run_demo_auto_approves_each_pending_booking() -> None:
    runner = StubRunner(
        run_results=[_answer("here's the answer"), _confirm("Book hvac")],
        confirm_results=[_answer("Booked!")],
    )
    out = io.StringIO()
    run_demo(runner, ["a question", "a booking"], out)
    assert len(runner.run_calls) == 2
    assert runner.confirm_calls == [("demo-2", "approve")]  # the demo auto-approves
    text = out.getvalue()
    assert "here's the answer" in text and "Booked!" in text


def test_trace_summary_includes_key_fields() -> None:
    trace = TurnTrace(channel="agent", intent="book", route="respond")
    trace.record_tool(ToolCallTrace(name="check_service_area", capability="read_only"))
    trace.record_tool(ToolCallTrace(name="create_booking", capability="mutating"))
    trace.committed = True
    trace.committed_booking_id = "BK-9"
    summary = _trace_summary(trace)
    assert "intent=book" in summary
    assert "create_booking*" in summary  # mutating marked with *
    assert "committed=BK-9" in summary
