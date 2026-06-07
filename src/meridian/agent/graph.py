"""Assemble the agent's LangGraph state machine.

The topology is the safety guarantee: ``commit`` (the only mutating node) is reachable *only*
through ``confirm`` (which interrupts for approval). There is no edge from planning straight to
commit, so a booking can never be created/changed without an explicit, approved confirmation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from ..tracing.trace import ToolCallTrace, TurnTrace
from .nodes import AgentNodes
from .state import AgentState


def _default_checkpointer() -> MemorySaver:
    """In-memory checkpointer that registers the agent's trace types with the msgpack allowlist.

    ``TurnTrace`` (and its nested ``ToolCallTrace``) ride in the checkpointed state so the trace
    survives the confirm interrupt. Registering them explicitly silences LangGraph's
    "unregistered type" deprecation warning and future-proofs against a strict-msgpack default —
    the built-in safe types stay allowed, so nothing else is affected.
    """
    serde = JsonPlusSerializer(allowed_msgpack_modules=[TurnTrace, ToolCallTrace])
    return MemorySaver(serde=serde)


def _carries_trace(node: Callable[[AgentState], dict[str, Any]]) -> Any:
    """Ensure a node's output always re-emits the (mutated) trace so it is checkpointed.

    Nodes mutate ``state['trace']`` in place; LangGraph only persists what a node RETURNS, so
    without this every trace write made before the confirm interrupt would be lost on the
    resumed turn. Returning the trace each step keeps it whole across the interrupt.
    """

    def wrapped(state: AgentState) -> dict[str, Any]:
        result = node(state)
        result.setdefault("trace", state.get("trace"))
        return result

    return wrapped


def build_graph(nodes: AgentNodes, checkpointer: Any | None = None) -> Any:
    """Compile the agent graph with a checkpointer (defaults to in-memory)."""
    graph = StateGraph(AgentState)

    graph.add_node("safety", _carries_trace(nodes.safety))
    graph.add_node("classify", _carries_trace(nodes.classify))
    graph.add_node("retrieve", _carries_trace(nodes.retrieve))
    graph.add_node("answer", _carries_trace(nodes.answer))
    graph.add_node("lookup", _carries_trace(nodes.lookup))
    graph.add_node("plan_booking", _carries_trace(nodes.plan_booking))
    graph.add_node("clarify", _carries_trace(nodes.clarify))
    graph.add_node("confirm", _carries_trace(nodes.confirm))
    graph.add_node("commit", _carries_trace(nodes.commit))
    graph.add_node("respond", _carries_trace(nodes.respond))
    graph.add_node("handoff", _carries_trace(nodes.handoff))

    graph.add_edge(START, "safety")
    graph.add_conditional_edges(
        "safety", nodes.route_after_safety, {"handoff": "handoff", "classify": "classify"}
    )
    graph.add_conditional_edges(
        "classify",
        nodes.route_after_classify,
        {
            "retrieve": "retrieve",
            "lookup": "lookup",
            "plan_booking": "plan_booking",
            "handoff": "handoff",
        },
    )
    graph.add_conditional_edges(
        "retrieve", nodes.route_after_retrieve, {"answer": "answer", "handoff": "handoff"}
    )
    graph.add_conditional_edges(
        "lookup", nodes.route_by_state, {"clarify": "clarify", "respond": "respond"}
    )
    graph.add_conditional_edges(
        "plan_booking",
        nodes.route_by_state,
        {"clarify": "clarify", "respond": "respond", "confirm": "confirm"},
    )
    # commit is reachable ONLY from confirm — the confirm-before-commit invariant, by topology.
    graph.add_conditional_edges(
        "confirm", nodes.route_by_state, {"commit": "commit", "respond": "respond"}
    )
    graph.add_edge("commit", "respond")
    graph.add_edge("answer", END)
    graph.add_edge("clarify", END)
    graph.add_edge("respond", END)
    graph.add_edge("handoff", END)

    return graph.compile(checkpointer=checkpointer or _default_checkpointer())
