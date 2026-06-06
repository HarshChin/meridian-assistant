"""Agent state + the classification schema for the LangGraph state machine.

The state is checkpointed per session (thread id), so multi-turn slot state and the
confirm-before-commit interrupt survive across turns. ``trace`` is the :class:`TurnTrace` the
runner returns and the eval inspects.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from ..domain.enums import JobType, ServiceType, Window
from ..tracing.trace import TurnTrace

Intent = Literal["knowledge_qa", "book", "reschedule", "cancel", "booking_status", "out_of_scope"]


class Classification(BaseModel):
    """Intent + booking slots extracted from the customer message (the LLM fills this).

    ``date_phrase`` is the RAW wording (e.g. "next Wednesday", "the 24th") — the agent resolves
    it to a concrete date in code, never the LLM, so date handling is deterministic.
    """

    intent: Intent = Field(description="The customer's intent.")
    service_type: ServiceType | None = None
    zip_code: str | None = Field(default=None, description="5-digit ZIP if stated.")
    job_type: JobType | None = None
    date_phrase: str | None = Field(
        default=None, description="Raw date wording as written; do NOT convert to a date."
    )
    window: Window | None = None
    booking_id: str | None = Field(default=None, description="BK-XXXXXXXX if stated.")
    customer_id: str | None = Field(default=None, description="Customer id if stated.")


class AgentState(TypedDict, total=False):
    """LangGraph state for one session (checkpointed)."""

    user_message: str
    channel: str
    now_iso: str
    intent: str
    slots: dict[str, Any]
    knowledge: dict[str, Any]
    proposed_action: dict[str, Any] | None
    confirmation_preview: str | None
    confirmation_decision: str | None
    route: str
    clarify_question: str
    respond_kind: str
    respond_facts: dict[str, Any]
    final_answer: str | None
    handoff: dict[str, Any] | None
    trace: TurnTrace
