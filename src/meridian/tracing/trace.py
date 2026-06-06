"""TurnTrace — the structured, inspectable record of one assistant turn.

Every decision the agent makes is recorded here: the route taken, what was retrieved and with
what confidence, every tool call (with its capability tag), the proposed mutating action and its
confirmation outcome, whether a mutation was committed, and any handoff. This is the contract the
eval harness asserts against (e.g. "emergency ⇒ handoff and no booking", "no mutation before an
approved confirm"), and it doubles as the per-turn observability log.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCallTrace(BaseModel):
    """One tool invocation as seen by the agent."""

    name: str
    capability: str = Field(description='"read_only" | "mutating".')
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    summary: str = ""
    citations: list[str] = Field(default_factory=list)


class TurnTrace(BaseModel):
    """The full trace of a single turn (built up by the graph nodes, returned by the runner)."""

    channel: str
    user_message: str = ""

    # classification / routing
    intent: str | None = None
    route: str | None = Field(default=None, description="answer | booking | clarify | handoff.")

    # retrieval / grounding
    retrieval_confidence: str | None = None
    citations: list[str] = Field(default_factory=list)
    grounded: bool | None = Field(
        default=None, description="True if the emitted knowledge answer carried an inline citation."
    )

    # tool use
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)

    # booking flow
    proposed_action: dict[str, Any] | None = Field(
        default=None, description="The mutating action staged for confirmation, if any."
    )
    confirmation_required: bool = False
    confirmation_decision: str | None = Field(default=None, description="approve | decline.")
    committed: bool = False
    committed_booking_id: str | None = None

    # safety / fallback
    emergency: bool = False
    handoff: bool = False
    handoff_category: str | None = None
    handoff_reason: str | None = None

    # output
    final_answer: str | None = None

    # observability
    notes: list[str] = Field(default_factory=list)

    def record_tool(self, call: ToolCallTrace) -> None:
        """Append a tool call and merge its citations into the turn's citations."""
        self.tool_calls.append(call)
        for citation in call.citations:
            if citation and citation not in self.citations:
                self.citations.append(citation)

    def note(self, message: str) -> None:
        """Append an observability note (decisions a reviewer/eval may want to see)."""
        self.notes.append(message)
