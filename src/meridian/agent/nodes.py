"""LangGraph nodes for the Meridian agent.

Code owns the booking-critical logic — relative-date resolution, coverage gating, fee math, and
the mutation itself — while the LLM classifies intent, extracts *raw* slots, and phrases replies
from code-supplied facts. Mutating tools run ONLY in ``commit``, which is reachable only after an
approved ``confirm`` interrupt, so confirm-before-commit is guaranteed by the graph topology.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.types import interrupt

from ..domain.enums import Channel
from ..guardrails import detect_emergency, fence_untrusted
from ..knowledge import branches
from ..knowledge.fees import cancellation_fee
from ..llm.client import LLMClient
from ..retrieval.confidence import Confidence
from ..tools import ToolRegistry, ToolResult
from ..tracing.trace import ToolCallTrace
from ..windows import resolve_relative_date
from .prompts import ANSWER_SYSTEM, CLARIFY_SYSTEM, CLASSIFY_SYSTEM, RESPOND_SYSTEM
from .state import AgentState, Classification

_APPROVE = {"approve", "yes", "y", "confirm", "ok", "proceed", "book it", "go ahead"}


@dataclass
class AgentContext:
    """Runtime dependencies for the agent nodes (built per session)."""

    llm: LLMClient
    registry: ToolRegistry
    channel: Channel


class AgentNodes:
    """The graph nodes, sharing one :class:`AgentContext`."""

    def __init__(self, ctx: AgentContext) -> None:
        """Bind the nodes to their runtime context."""
        self._ctx = ctx

    # ------------------------------------------------------------------ helpers
    def _run_tool(
        self, state: AgentState, name: str, args: dict[str, Any], *, allow_mutations: bool = False
    ) -> ToolResult:
        result = self._ctx.registry.execute(name, args, allow_mutations=allow_mutations)
        cap = "mutating" if self._ctx.registry.is_mutating(name) else "read_only"
        state["trace"].record_tool(
            ToolCallTrace(
                name=name,
                capability=cap,
                args=args,
                ok=result.ok,
                summary=result.summary,
                citations=result.citations,
            )
        )
        return result

    def _now(self, state: AgentState) -> datetime:
        return datetime.fromisoformat(state["now_iso"])

    @staticmethod
    def _clarify(question: str) -> dict[str, Any]:
        return {"route": "clarify", "clarify_question": question}

    @staticmethod
    def _respond(kind: str, facts: dict[str, Any]) -> dict[str, Any]:
        return {"route": "respond", "respond_kind": kind, "respond_facts": facts}

    # ------------------------------------------------------------------ nodes
    def safety(self, state: AgentState) -> dict[str, Any]:
        """Rules-first emergency screen (runs first); an emergency short-circuits to handoff."""
        assessment = detect_emergency(state["user_message"])
        if assessment.is_emergency:
            category = (assessment.category or "").replace("_", " ")
            state["trace"].emergency = True
            state["trace"].note(f"emergency rule: {assessment.category} ('{assessment.matched}')")
            return {
                "route": "handoff",
                "handoff": {
                    "category": "emergency",
                    "reason": f"Possible {category} emergency.",
                    "emergency_line": branches.emergency_line(),
                },
            }
        return {"route": "continue"}

    def classify(self, state: AgentState) -> dict[str, Any]:
        """Classify intent + extract raw slots (date stays a phrase, resolved later in code)."""
        cls = self._ctx.llm.structured(CLASSIFY_SYSTEM, state["user_message"], Classification)
        state["trace"].intent = cls.intent
        return {"intent": cls.intent, "slots": cls.model_dump(mode="json", exclude={"intent"})}

    def retrieve(self, state: AgentState) -> dict[str, Any]:
        """Retrieve grounding for a knowledge question (via the knowledge_search tool)."""
        result = self._run_tool(state, "knowledge_search", {"query": state["user_message"]})
        state["trace"].retrieval_confidence = result.data.get("confidence")
        return {"knowledge": result.data}

    def answer(self, state: AgentState) -> dict[str, Any]:
        """Compose a grounded, cited answer strictly from the retrieved passages."""
        chunks = state.get("knowledge", {}).get("chunks", [])
        passages = "\n\n".join(
            fence_untrusted(f"[source: {c['citation']}]\n{c['text']}") for c in chunks
        )
        user = f"Customer question:\n{state['user_message']}\n\nKnowledge passages:\n{passages}"
        text = self._ctx.llm.complete(ANSWER_SYSTEM, user)
        state["trace"].route = "answer"
        state["trace"].final_answer = text
        return {"final_answer": text, "route": "answer"}

    def lookup(self, state: AgentState) -> dict[str, Any]:
        """Look up an existing booking's status (read-only)."""
        slots = state.get("slots", {})
        booking_id = slots.get("booking_id")
        if not booking_id:
            return self._clarify("Which booking id (BK-XXXXXXXX) would you like the status of?")
        result = self._run_tool(
            state,
            "lookup_booking",
            {"booking_id": booking_id, "customer_id": slots.get("customer_id")},
        )
        return self._respond("booking_status", {"lookup": result.data, "ok": result.ok})

    def plan_booking(self, state: AgentState) -> dict[str, Any]:
        """Resolve slots in code, gate on coverage, and stage a mutating action for confirmation."""
        intent = state["intent"]
        slots = state.get("slots", {})
        now = self._now(state)
        resolved = (
            resolve_relative_date(slots["date_phrase"], now) if slots.get("date_phrase") else None
        )

        if intent == "book":
            if not slots.get("zip_code") or not slots.get("service_type"):
                return self._clarify(
                    "What's the service ZIP code, and is this for HVAC, plumbing, or electrical?"
                )
            if resolved is None:
                return self._clarify("What date would you like the appointment?")
            coverage = self._run_tool(
                state,
                "check_service_area",
                {"zip_code": slots["zip_code"], "service_type": slots["service_type"]},
            )
            if coverage.data.get("eligibility") in ("no", "unknown"):
                return self._respond("coverage_blocked", {"coverage": coverage.data})
            args: dict[str, Any] = {
                "service_type": slots["service_type"],
                "job_type": slots.get("job_type") or "diagnostic",
                "zip_code": slots["zip_code"],
                "preferred_date": resolved.isoformat(),
                "preferred_window": slots.get("window") or "first_available",
                "customer_id": slots.get("customer_id"),
            }
            action = {"tool": "create_booking", "args": args, "coverage": coverage.data}
            preview = (
                f"Book {args['service_type']} ({args['job_type']}) at ZIP "
                f"{args['zip_code']} on {args['preferred_date']} ({args['preferred_window']})."
            )
            return {"route": "confirm", "proposed_action": action, "confirmation_preview": preview}

        # reschedule / cancel
        booking_id = slots.get("booking_id")
        if not booking_id:
            return self._clarify("Which booking id (BK-XXXXXXXX) should I update?")
        if intent == "reschedule":
            if resolved is None or not slots.get("window"):
                return self._clarify("What new date and time window (morning/midday/afternoon)?")
            action = {
                "tool": "modify_booking",
                "args": {
                    "booking_id": booking_id,
                    "action": "reschedule",
                    "new_date": resolved.isoformat(),
                    "new_window": slots["window"],
                },
            }
            preview = f"Reschedule {booking_id} to {resolved.isoformat()} ({slots['window']})."
        else:  # cancel
            action = {
                "tool": "modify_booking",
                "args": {"booking_id": booking_id, "action": "cancel"},
            }
            fee = self._cancel_fee_preview(booking_id, now)
            preview = f"Cancel booking {booking_id}." + (
                f" A ${fee} cancellation fee would apply."
                if fee
                else " No cancellation fee applies."
            )
        return {"route": "confirm", "proposed_action": action, "confirmation_preview": preview}

    def _cancel_fee_preview(self, booking_id: str, now: datetime) -> int:
        """Preview the cancellation fee a cancel would incur (read-only; reuses the schedule)."""
        look = self._ctx.registry.execute("lookup_booking", {"booking_id": booking_id})
        window = look.data.get("appointment_window") if look.ok else None
        if not window:
            return 0
        appt = datetime.fromisoformat(f"{window['date']}T{window['start_time']}:00").replace(
            tzinfo=now.tzinfo
        )
        return cancellation_fee((appt - now).total_seconds() / 3600.0)

    def clarify(self, state: AgentState) -> dict[str, Any]:
        """Ask the customer one concise question for the missing slot."""
        question = state.get("clarify_question", "Could you share a bit more detail?")
        user = f"Customer said: {state['user_message']}\nAsk them, in one sentence: {question}"
        text = self._ctx.llm.complete(CLARIFY_SYSTEM, user)
        state["trace"].route = "clarify"
        state["trace"].final_answer = text
        return {"final_answer": text}

    def confirm(self, state: AgentState) -> dict[str, Any]:
        """Pause for explicit approval (LangGraph interrupt) before any mutation."""
        state["trace"].confirmation_required = True
        state["trace"].proposed_action = state.get("proposed_action")
        decision = interrupt(
            {
                "preview": state.get("confirmation_preview"),
                "proposed_action": state.get("proposed_action"),
            }
        )
        approved = str(decision).strip().lower() in _APPROVE
        state["trace"].confirmation_decision = "approve" if approved else "decline"
        if approved:
            return {"confirmation_decision": "approve", "route": "commit"}
        return {
            "confirmation_decision": "decline",
            "route": "respond",
            "respond_kind": "declined",
            "respond_facts": {},
        }

    def commit(self, state: AgentState) -> dict[str, Any]:
        """Execute the approved mutating action — the ONLY place a booking is created/changed."""
        action = state["proposed_action"] or {}
        result = self._run_tool(state, action["tool"], action["args"], allow_mutations=True)
        data = result.data
        status = data.get("status")
        if result.ok:
            state["trace"].committed = True
            state["trace"].committed_booking_id = data.get("booking_id")
        return self._respond(
            "booking_result",
            {
                "succeeded": result.ok
                and status in ("confirmed", "pending_availability", "rescheduled", "cancelled"),
                "status": status,
                "booking_id": data.get("booking_id"),
                "assigned_branch": data.get("assigned_branch"),
                "appointment_window": data.get("appointment_window")
                or data.get("new_appointment_window"),
                "fee_applied": data.get("fee_applied"),
                "tech_name": data.get("tech_name"),
            },
        )

    def respond(self, state: AgentState) -> dict[str, Any]:
        """Compose the final customer reply from code-supplied facts (no invented figures)."""
        kind = state.get("respond_kind", "general")
        facts = state.get("respond_facts", {})
        user = (
            f"Customer said: {state['user_message']}\n\nSituation: {kind}\n"
            f"Facts:\n{json.dumps(facts, default=str, indent=2)}"
        )
        text = self._ctx.llm.complete(RESPOND_SYSTEM, user)
        state["trace"].route = "respond"
        state["trace"].final_answer = text
        return {"final_answer": text}

    def handoff(self, state: AgentState) -> dict[str, Any]:
        """Hand off to a human (emergency or out-of-scope/abstention), with the right message."""
        payload = state.get("handoff") or {"category": "out_of_scope", "reason": "Out of scope."}
        trace = state["trace"]
        trace.handoff = True
        trace.handoff_category = payload.get("category")
        trace.handoff_reason = payload.get("reason")
        trace.route = "handoff"
        if payload.get("category") == "emergency":
            message = (
                "This sounds like an emergency. Please call our 24/7 emergency line now: "
                f"{payload.get('emergency_line')}. I'm flagging this for immediate human help."
            )
        else:
            message = (
                "I'm not able to help with that directly — let me connect you with a Meridian "
                "specialist who can."
            )
        trace.final_answer = message
        return {"final_answer": message, "route": "handoff"}

    # ------------------------------------------------------------------ routers
    @staticmethod
    def route_after_safety(state: AgentState) -> str:
        """Route to handoff on an emergency, else to classification."""
        return "handoff" if state.get("route") == "handoff" else "classify"

    @staticmethod
    def route_after_classify(state: AgentState) -> str:
        """Route by intent to retrieval / lookup / booking / handoff."""
        return {
            "knowledge_qa": "retrieve",
            "booking_status": "lookup",
            "book": "plan_booking",
            "reschedule": "plan_booking",
            "cancel": "plan_booking",
            "out_of_scope": "handoff",
        }.get(state.get("intent", "out_of_scope"), "handoff")

    @staticmethod
    def route_after_retrieve(state: AgentState) -> str:
        """Abstain to handoff when retrieval confidence is LOW, else answer from the chunks."""
        return (
            "handoff"
            if state.get("knowledge", {}).get("confidence") == Confidence.LOW.value
            else "answer"
        )

    @staticmethod
    def route_by_state(state: AgentState) -> str:
        """Follow the route a node set on the state (clarify / respond / confirm / commit)."""
        return state.get("route", "respond")
