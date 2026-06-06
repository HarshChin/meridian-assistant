"""AgentRunner — drives the graph and surfaces the confirm-before-commit interrupt across turns.

``run_turn`` runs a fresh message; if the graph pauses at ``confirm`` it returns a
``confirmation_required`` result. ``confirm_turn`` resumes the paused graph with the customer's
approve/decline decision. State (including the pending action) is checkpointed per session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from ..api_client.base import BookingClient
from ..clock import Clock
from ..domain.enums import Channel
from ..llm.client import LLMClient
from ..retrieval.retriever import HybridRetriever
from ..tools import build_registry
from ..tracing.trace import TurnTrace
from .graph import build_graph
from .nodes import AgentContext, AgentNodes


@dataclass
class TurnResult:
    """The outcome of one turn the caller (CLI / web / eval) renders."""

    kind: str  # "answer" | "confirmation_required" | "handoff"
    message: str
    trace: TurnTrace | None = None
    preview: str | None = None
    proposed_action: dict[str, Any] | None = None


class AgentRunner:
    """Builds the agent graph for a transport and runs/​resumes turns."""

    def __init__(
        self,
        llm: LLMClient,
        retriever: HybridRetriever,
        booking_client: BookingClient,
        clock: Clock,
        channel: Channel = Channel.AGENT,
    ) -> None:
        """Wire the registry (channel + booking client) and compile the graph."""
        self._clock = clock
        self._channel = channel
        registry = build_registry(retriever, booking_client, channel)
        self._graph = build_graph(
            AgentNodes(AgentContext(llm=llm, registry=registry, channel=channel))
        )

    def run_turn(self, session_id: str, message: str) -> TurnResult:
        """Run a new customer message; may return an answer, a handoff, or a confirmation prompt."""
        trace = TurnTrace(channel=self._channel.value, user_message=message)
        state = {
            "user_message": message,
            "channel": self._channel.value,
            "now_iso": self._clock.now().isoformat(),
            "trace": trace,
        }
        config = {"configurable": {"thread_id": session_id}}
        result = self._graph.invoke(state, config)
        return self._to_result(result, config)

    def confirm_turn(self, session_id: str, decision: str) -> TurnResult:
        """Resume a paused booking with the customer's approve/decline decision."""
        config = {"configurable": {"thread_id": session_id}}
        result = self._graph.invoke(Command(resume=decision), config)
        return self._to_result(result, config)

    def _to_result(self, result: dict[str, Any], config: dict[str, Any]) -> TurnResult:
        trace = result.get("trace")
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            payload = payload if isinstance(payload, dict) else {}
            if isinstance(trace, TurnTrace):
                trace.confirmation_required = True
                trace.route = "confirm"
            return TurnResult(
                kind="confirmation_required",
                message=str(payload.get("preview") or "Shall I proceed?"),
                trace=trace if isinstance(trace, TurnTrace) else None,
                preview=payload.get("preview"),
                proposed_action=payload.get("proposed_action"),
            )
        kind = "handoff" if result.get("route") == "handoff" else "answer"
        return TurnResult(
            kind=kind,
            message=str(result.get("final_answer") or ""),
            trace=trace if isinstance(trace, TurnTrace) else None,
        )
