"""Interactive CLI for the Meridian assistant — the canonical interface + scripted demo driver.

This module is the **composition root**: it wires the agent (LLM client + retriever) to the
in-process Booking double and a clock, so importing ``app/`` here is intentional — the entry
point owns the wiring; the library modules never depend on the app.

The turn loop is I/O-injected (reader / writer / a confirmation ``decide`` callback) so the
confirm-before-commit interaction is unit-testable without a real LLM, and ``--demo`` replays a
curated script deterministically on a frozen clock for ``make demo`` and a recorded transcript.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import TextIO

from app.seed import build_seed_store
from app.service import BookingService

from .agent import AgentRunner, TurnResult
from .clock import DEMO_NOW, Clock, FrozenClock, SystemClock
from .domain.enums import Channel
from .llm.client import LLMClient
from .retrieval.retriever import HybridRetriever
from .tracing.trace import TurnTrace

DEMO_SCRIPT: list[str] = [
    "What's the difference between the Gold and Platinum maintenance plans?",
    "Is there a surcharge for a Sunday appointment?",
    "There's a burning smell coming from my electrical panel!",
    "Book an HVAC tune-up at ZIP 22030 for May 15 2026 morning. My customer id is CID-7000.",
    "Book an electrical repair at ZIP 20147 for May 16 2026 morning. Customer id CID-7001.",
    "What's the status of booking BK-00512883?",
]
"""Curated, capability-spanning script for ``--demo`` (knowledge, emergency, booking, status)."""


def build_runner(*, frozen_clock: bool = True, channel: Channel = Channel.AGENT) -> AgentRunner:
    """Wire the agent runner with the in-process Booking double and a clock.

    The demo runs on a frozen 2026-05-01 clock (bookable window 2026-05-01..2026-06-30); the seed
    bookings are dated relative to that clock so status/reschedule/cancel stay coherent. With
    ``--system-clock`` the real time is used and the seed follows it too.
    """
    clock: Clock = FrozenClock(DEMO_NOW) if frozen_clock else SystemClock()
    return AgentRunner(
        llm=LLMClient(),
        retriever=HybridRetriever.load(),
        booking_client=BookingService(clock=clock, store=build_seed_store(clock.now())),
        clock=clock,
        channel=channel,
    )


def _trace_summary(trace: TurnTrace) -> str:
    """A compact one-line trace summary for the ``--trace`` view."""
    tools = ",".join(
        f"{c.name}{'*' if c.capability == 'mutating' else ''}" for c in trace.tool_calls
    )
    bits = [f"intent={trace.intent}", f"route={trace.route}"]
    if tools:
        bits.append(f"tools=[{tools}]")
    if trace.confirmation_required:
        bits.append(f"confirm={trace.confirmation_decision or 'pending'}")
    if trace.committed:
        bits.append(f"committed={trace.committed_booking_id}")
    if trace.handoff:
        bits.append(f"handoff={trace.handoff_category}")
    return "  trace: " + " ".join(bits)


def _render(result: TurnResult, out: TextIO, *, show_trace: bool) -> None:
    """Print the assistant's message, its citations, and (optionally) a trace summary."""
    out.write(f"\nassistant: {result.message}\n")
    if result.trace and result.trace.citations:
        out.write("  sources: " + " | ".join(result.trace.citations) + "\n")
    if show_trace and result.trace:
        out.write(_trace_summary(result.trace) + "\n")


def handle_turn(
    runner: AgentRunner,
    session_id: str,
    message: str,
    *,
    decide: Callable[[TurnResult], str],
    out: TextIO,
    show_trace: bool = False,
) -> TurnResult:
    """Run one message and drive the confirm-before-commit loop to a terminal result."""
    result = runner.run_turn(session_id, message)
    _render(result, out, show_trace=show_trace)
    while result.kind == "confirmation_required":
        decision = decide(result)
        out.write(f"  [decision: {decision}]\n")
        result = runner.confirm_turn(session_id, decision)
        _render(result, out, show_trace=show_trace)
    return result


def run_demo(
    runner: AgentRunner, script: list[str], out: TextIO, *, show_trace: bool = False
) -> None:
    """Replay a scripted set of messages, auto-approving any confirmation (deterministic demo)."""
    for index, message in enumerate(script, start=1):
        out.write(f"\n=== [{index}] you: {message}\n")
        handle_turn(
            runner,
            f"demo-{index}",
            message,
            decide=lambda _r: "approve",
            out=out,
            show_trace=show_trace,
        )


def _interactive_decide(result: TurnResult) -> str:
    """Prompt the operator to approve/decline a pending booking (interactive REPL)."""
    answer = input(f"  Confirm: {result.preview} [y/N] ").strip().lower()
    return "approve" if answer in ("y", "yes", "approve") else "decline"


def repl(
    runner: AgentRunner, out: TextIO, *, auto_approve: bool = False, show_trace: bool = False
) -> None:
    """Interactive read-eval-print loop over a single session."""
    out.write("Meridian assistant — type a message, or /trace, /quit.\n")
    decide: Callable[[TurnResult], str] = (
        (lambda _r: "approve") if auto_approve else _interactive_decide
    )
    last: TurnResult | None = None
    while True:
        try:
            message = input("\nyou: ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\nGoodbye!\n")
            return
        if not message:
            continue
        if message in ("/quit", "/exit"):
            return
        if message == "/trace":
            out.write(
                (_trace_summary(last.trace) if last and last.trace else "  (no trace yet)") + "\n"
            )
            continue
        last = handle_turn(runner, "cli", message, decide=decide, out=out, show_trace=show_trace)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Meridian assistant CLI.")
    parser.add_argument("--demo", action="store_true", help="Replay the scripted demo and exit.")
    parser.add_argument(
        "--system-clock",
        action="store_true",
        help="Use the real wall clock instead of the frozen 2026-05-01 demo clock. The seed "
        "bookings are dated relative to the clock, so this stays coherent with the real date.",
    )
    parser.add_argument(
        "--channel", default="agent", choices=[c.value for c in Channel], help="Inbound channel."
    )
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve confirmations.")
    parser.add_argument(
        "--trace", action="store_true", help="Show a trace summary after each turn."
    )
    args = parser.parse_args(argv)

    runner = build_runner(frozen_clock=not args.system_clock, channel=Channel(args.channel))
    out = sys.stdout
    if args.demo:
        run_demo(runner, DEMO_SCRIPT, out, show_trace=args.trace)
    else:
        repl(runner, out, auto_approve=args.auto_approve, show_trace=args.trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
