"""LangGraph nodes for the Meridian agent.

Code owns the booking-critical logic — relative-date resolution, coverage gating, fee math, and
the mutation itself — while the LLM classifies intent, extracts *raw* slots, and phrases replies
from code-supplied facts. Mutating tools run ONLY in ``commit``, which is reachable only after an
approved ``confirm`` interrupt, so confirm-before-commit is guaranteed by the graph topology.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from langgraph.types import interrupt

from ..api_contract import MAX_ADVANCE_DAYS
from ..clock import EASTERN
from ..domain.booking import CustomerInfo
from ..domain.enums import Channel
from ..guardrails import EmergencyAssessment, EmergencyCheck, detect_emergency, fence_untrusted
from ..knowledge import branches
from ..knowledge.fees import cancellation_fee
from ..llm.client import LLMClient, LLMUnavailableError
from ..retrieval.confidence import Confidence
from ..tools import ToolRegistry, ToolResult
from ..tracing.trace import ToolCallTrace
from ..windows import resolve_relative_date, within_advance_window
from .prompts import (
    ANSWER_SYSTEM,
    CLARIFY_SYSTEM,
    CLASSIFY_SYSTEM,
    CONTACT_SYSTEM,
    EMERGENCY_SYSTEM,
    GENERAL_SYSTEM,
    RESPOND_SYSTEM,
)
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
    def _emergency_llm_union(self, message: str) -> EmergencyAssessment | None:
        """LLM paraphrase-catch: may only ADD an emergency the rules missed, never veto one."""
        try:
            check = self._ctx.llm.structured(EMERGENCY_SYSTEM, message, EmergencyCheck)
        except LLMUnavailableError:
            return None  # rules-only fallback when no key/cache (the LLM leg is best-effort)
        if check.is_emergency:
            return EmergencyAssessment(
                is_emergency=True, category=check.category or "llm_detected", matched="llm"
            )
        return None

    def safety(self, state: AgentState) -> dict[str, Any]:
        """Rules-first emergency screen + an LLM paraphrase union (adds only); else continue."""
        message = state["user_message"]
        assessment = detect_emergency(message)
        if not assessment.is_emergency:
            assessment = self._emergency_llm_union(message) or assessment
        if assessment.is_emergency:
            category = (assessment.category or "emergency").replace("_", " ")
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
        trace = state["trace"]
        # Deterministic groundedness gate: an answer with no inline citation is not grounded —
        # abstain to a human rather than present an uncited claim as documented fact.
        if "[source:" not in text:
            trace.grounded = False
            trace.handoff = True
            trace.handoff_category = "low_confidence"
            trace.handoff_reason = "Could not ground an answer in the documents."
            trace.route = "handoff"
            message = (
                "I want to be sure I give you accurate information, and I can't confirm that "
                "from our documents — let me connect you with a Meridian specialist."
            )
            trace.final_answer = message
            return {"final_answer": message, "route": "handoff"}
        trace.grounded = True
        trace.route = "answer"
        trace.final_answer = text
        return {"final_answer": text, "route": "answer"}

    def lookup(self, state: AgentState) -> dict[str, Any]:
        """Look up a booking's status; owner-only PII is gated on a matching customer_id."""
        slots = state.get("slots", {})
        booking_id = slots.get("booking_id")
        if not booking_id:
            return self._clarify("Which booking id (BK-XXXXXXXX) would you like the status of?")
        customer_id = slots.get("customer_id")
        result = self._run_tool(
            state, "lookup_booking", {"booking_id": booking_id, "customer_id": customer_id}
        )
        data = dict(result.data)
        verified = bool(customer_id) and result.ok and "error" not in data
        facts: dict[str, Any] = {"lookup": data, "ok": result.ok, "ownership_verified": verified}
        if result.ok and not verified:
            # Owner-only PII (technician name, notes, invoice) is withheld until the customer
            # verifies the booking's customer id. Drop the withheld nulls so the reply can't
            # misread them as "not assigned", and flag what needs verification so the reply asks.
            for field in ("tech_name", "notes", "invoice_total"):
                data.pop(field, None)
            facts["restricted_pii"] = ["technician name", "appointment notes", "invoice total"]
        return self._respond("booking_status", facts)

    def plan_booking(self, state: AgentState) -> dict[str, Any]:
        """Resolve slots in code, gate on coverage, and stage a mutating action for confirmation."""
        intent = state["intent"]
        slots = state.get("slots", {})
        now = self._now(state)
        date_phrase = slots.get("date_phrase")
        # Don't trust an ISO date the customer did not literally type — if the LLM normalised a
        # relative phrase into a calendar date, ignore it so the date is resolved in code (or we
        # clarify). Relative phrases are resolved deterministically by resolve_relative_date.
        iso = re.search(r"\d{4}-\d{2}-\d{2}", date_phrase or "")
        if iso and iso.group(0) not in state["user_message"]:
            date_phrase = None
        resolved = resolve_relative_date(date_phrase, now) if date_phrase else None

        if intent == "book":
            if not slots.get("zip_code") or not slots.get("service_type"):
                return self._clarify(
                    "What's the service ZIP code, and is this for HVAC, plumbing, or electrical?"
                )
            if resolved is None:
                return self._clarify("What date would you like the appointment?")
            if not within_advance_window(resolved, now):
                limit = (now.date() + timedelta(days=MAX_ADVANCE_DAYS)).isoformat()
                return self._clarify(
                    f"The requested date {resolved.isoformat()} isn't bookable — we schedule from "
                    f"{now.date().isoformat()} up to {limit}; ask for a date in that range."
                )
            coverage = self._run_tool(
                state,
                "check_service_area",
                {"zip_code": slots["zip_code"], "service_type": slots["service_type"]},
            )
            if coverage.data.get("eligibility") in ("no", "unknown"):
                return self._respond("coverage_blocked", {"coverage": coverage.data})
            customer_id = slots.get("customer_id")
            # Identity: a customer_id, or contact details (name/phone/email) extracted from the
            # message. Ask only if neither is present — don't make a customer who already gave
            # their details repeat them.
            customer_info = None if customer_id else self._extract_customer_info(state)
            if not customer_id and not customer_info:
                return self._clarify(
                    "Could I get the customer id, or a name and phone number to book under?"
                )
            args: dict[str, Any] = {
                "service_type": slots["service_type"],
                "job_type": slots.get("job_type") or "diagnostic",
                "zip_code": slots["zip_code"],
                "preferred_date": resolved.isoformat(),
                "preferred_window": slots.get("window") or "first_available",
                "customer_id": customer_id,
                "customer_info": customer_info,
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
        # Verify the booking exists before asking for scheduling details — a wrong/unknown id
        # should get "I can't find it", not a date/time-window question.
        look = self._ctx.registry.execute("lookup_booking", {"booking_id": booking_id})
        if not look.ok:
            return self._clarify(
                f"I couldn't find a booking with id {booking_id} — could you double-check it?"
            )
        if intent == "reschedule":
            window = slots.get("window")
            # Window-only reschedule ("move me to the afternoon, same day"): the customer gave a
            # new time window but no new date, so keep the booking's existing date and just change
            # the window. Fall back to asking only if we still can't determine a date or window.
            if resolved is None and window:
                current = look.data.get("appointment_window") or {}
                if current.get("date"):
                    resolved = date.fromisoformat(current["date"])
            if resolved is None or not window:
                return self._clarify(
                    "What new date and time window (morning/midday/afternoon) would you like?"
                )
            if not within_advance_window(resolved, now):
                limit = (now.date() + timedelta(days=MAX_ADVANCE_DAYS)).isoformat()
                return self._clarify(
                    f"That date ({resolved.isoformat()}) isn't bookable — we schedule from "
                    f"{now.date().isoformat()} up to {limit}; what new date would you like?"
                )
            action = {
                "tool": "modify_booking",
                "args": {
                    "booking_id": booking_id,
                    "action": "reschedule",
                    "new_date": resolved.isoformat(),
                    "new_window": window,
                },
            }
            preview = f"Reschedule {booking_id} to {resolved.isoformat()} ({window})."
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
        # Build the appointment in EASTERN (the tz the BookingService uses) so the previewed fee
        # matches the fee the service will actually charge, even across a DST boundary.
        appt = datetime.fromisoformat(f"{window['date']}T{window['start_time']}:00").replace(
            tzinfo=EASTERN
        )
        return cancellation_fee((appt - now).total_seconds() / 3600.0)

    def _extract_customer_info(self, state: AgentState) -> dict[str, Any] | None:
        """Extract booking contact details from the message when no customer_id was given."""
        try:
            info = self._ctx.llm.structured(CONTACT_SYSTEM, state["user_message"], CustomerInfo)
        except LLMUnavailableError:
            return None  # keyless with no cached extraction → fall back to asking for identity
        details = info.model_dump(mode="json", exclude_none=True)
        return details or None

    def general(self, state: AgentState) -> dict[str, Any]:
        """Answer a greeting / conversational message in-role (no retrieval, no booking)."""
        text = self._ctx.llm.complete(GENERAL_SYSTEM, state["user_message"])
        state["trace"].route = "general"
        state["trace"].final_answer = text
        return {"final_answer": text, "route": "general"}

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
        # Defense-in-depth: never mutate without an approval recorded on THIS turn. The graph
        # topology already guarantees commit is only reached via confirm, but this makes
        # confirm-before-commit a per-action invariant rather than a purely topological one.
        if state.get("confirmation_decision") != "approve":
            return self._respond("declined", {})
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
            "general": "general",
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
