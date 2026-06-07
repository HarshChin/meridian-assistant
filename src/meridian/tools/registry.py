"""Build the tool registry, wiring each tool's handler to its runtime dependencies.

The registry is constructed per session with the inbound ``channel`` and a ``BookingClient``
(the in-process service for the CLI/eval, or the HTTP client for the web demo). Read-only tools
are available everywhere; the two mutating tools are tagged so they can run only in ``commit``.
"""

from __future__ import annotations

from ..api_client.base import BookingClient
from ..domain.enums import Channel
from ..retrieval.retriever import HybridRetriever
from . import booking_tools, knowledge_tools
from .base import Capability, Tool, ToolRegistry


def build_registry(
    retriever: HybridRetriever,
    booking_client: BookingClient,
    channel: Channel = Channel.AGENT,
) -> ToolRegistry:
    """Construct the agent's tool registry for one session."""
    from .schemas import (
        CheckServiceAreaArgs,
        CreateBookingArgs,
        EscalateArgs,
        KnowledgeSearchArgs,
        LookupBookingArgs,
        ModifyBookingArgs,
        QuoteFeeArgs,
    )

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="knowledge_search",
            description=(
                "Search the knowledge base and return grounded passages with citations. Use for "
                "policy, FAQ, warranty, payment, and pricing-band questions; answer only from what "
                "it returns, and hand off if confidence is low."
            ),
            capability=Capability.READ_ONLY,
            args_model=KnowledgeSearchArgs,
            handler=lambda a: knowledge_tools.knowledge_search(retriever, a),
        )
    )
    registry.register(
        Tool(
            name="check_service_area",
            description=(
                "Check whether a ZIP + service line is in a documented service area "
                "(yes / pending / no / unknown). Always call this before attempting a booking."
            ),
            capability=Capability.READ_ONLY,
            args_model=CheckServiceAreaArgs,
            handler=lambda a: knowledge_tools.check_service_area(a),
        )
    )
    registry.register(
        Tool(
            name="quote_fee",
            description=(
                "Compute an EXACT fee — diagnostic, emergency_dispatch, cancellation, or "
                "after_hours_surcharge — instead of guessing a number from prose."
            ),
            capability=Capability.READ_ONLY,
            args_model=QuoteFeeArgs,
            handler=lambda a: knowledge_tools.quote_fee(a),
        )
    )
    registry.register(
        Tool(
            name="lookup_booking",
            description=(
                "Look up an existing booking by id (e.g. BK-001). Pass the customer_id to "
                "reveal owner-only details such as technician name, notes, and invoice total."
            ),
            capability=Capability.READ_ONLY,
            args_model=LookupBookingArgs,
            handler=lambda a: booking_tools.lookup_booking(booking_client, a),
        )
    )
    registry.register(
        Tool(
            name="escalate_to_human",
            description=(
                "Hand off to a human agent: emergencies, out-of-scope requests, low confidence, "
                "missing information, or fee disputes. Use instead of guessing."
            ),
            capability=Capability.READ_ONLY,
            args_model=EscalateArgs,
            handler=lambda a: booking_tools.escalate_to_human(a),
        )
    )
    registry.register(
        Tool(
            name="create_booking",
            description=(
                "Create a booking. MUTATING — it runs only after the customer explicitly confirms, "
                "in the commit step. Check service-area eligibility first."
            ),
            capability=Capability.MUTATING,
            args_model=CreateBookingArgs,
            handler=lambda a: booking_tools.create_booking(booking_client, channel, a),
        )
    )
    registry.register(
        Tool(
            name="modify_booking",
            description=(
                "Reschedule or cancel an existing booking. MUTATING — it runs only after the "
                "customer explicitly confirms, in the commit step."
            ),
            capability=Capability.MUTATING,
            args_model=ModifyBookingArgs,
            handler=lambda a: booking_tools.modify_booking(booking_client, a),
        )
    )
    return registry
