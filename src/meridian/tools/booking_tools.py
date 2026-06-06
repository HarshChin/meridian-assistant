"""Booking tools: a read-only lookup, the two mutating booking actions, and the handoff signal.

``create_booking`` and ``modify_booking`` are tagged MUTATING in the registry, so they can only
execute in the agent's confirmed ``commit`` step. They construct the typed contract requests and
translate the contract's typed errors into customer-safe :class:`ToolResult`s rather than raising.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..api_client.base import BookingClient
from ..api_client.models import CreateBookingRequest, ModifyRequest
from ..domain.enums import Channel
from ..domain.errors import BookingNotFoundError, InvalidInputError, OwnershipError
from .base import ToolResult
from .schemas import CreateBookingArgs, EscalateArgs, LookupBookingArgs, ModifyBookingArgs


def lookup_booking(client: BookingClient, args: LookupBookingArgs) -> ToolResult:
    """Look up a booking; PII is revealed only when ``customer_id`` matches the owner."""
    try:
        resp = client.get_booking(args.booking_id, args.customer_id)
    except BookingNotFoundError:
        return ToolResult(
            tool="lookup_booking",
            ok=False,
            summary=f"No booking found for {args.booking_id}.",
            data={"error": "not_found", "booking_id": args.booking_id},
        )
    except OwnershipError:
        return ToolResult(
            tool="lookup_booking",
            ok=False,
            summary="Cannot share details: the customer id does not match this booking.",
            data={"error": "ownership"},
        )
    return ToolResult(
        tool="lookup_booking",
        ok=True,
        summary=f"Booking {resp.booking_id} is {resp.status.value}.",
        data=resp.model_dump(mode="json"),
    )


def create_booking(client: BookingClient, channel: Channel, args: CreateBookingArgs) -> ToolResult:
    """Create a booking on the inbound ``channel`` (mutating; commit-only)."""
    try:
        req = CreateBookingRequest(
            customer_id=args.customer_id,
            customer_info=args.customer_info,
            service_type=args.service_type,
            job_type=args.job_type,
            zip_code=args.zip_code,
            preferred_date=args.preferred_date,
            preferred_window=args.preferred_window,
            notes=args.notes,
            channel=channel,
        )
    except ValidationError:
        return ToolResult(
            tool="create_booking",
            ok=False,
            summary="Need a customer id or contact details before booking.",
            data={"error": "missing_identity"},
        )
    try:
        resp = client.create_booking(req)
    except InvalidInputError as exc:
        return ToolResult(
            tool="create_booking", ok=False, summary=str(exc), data={"error": "invalid_input"}
        )
    return ToolResult(
        tool="create_booking",
        ok=True,
        summary=f"{resp.status.value}: booking {resp.booking_id}.",
        data=resp.model_dump(mode="json"),
    )


def modify_booking(client: BookingClient, args: ModifyBookingArgs) -> ToolResult:
    """Reschedule or cancel a booking (mutating; commit-only)."""
    try:
        req = ModifyRequest(
            action=args.action,
            new_date=args.new_date,
            new_window=args.new_window,
            cancel_reason=args.cancel_reason,
            notes=args.notes,
        )
    except ValidationError as exc:
        return ToolResult(
            tool="modify_booking", ok=False, summary=str(exc), data={"error": "invalid_input"}
        )
    try:
        resp = client.modify_booking(args.booking_id, req)
    except BookingNotFoundError:
        return ToolResult(
            tool="modify_booking",
            ok=False,
            summary=f"No booking found for {args.booking_id}.",
            data={"error": "not_found"},
        )
    except InvalidInputError as exc:
        return ToolResult(
            tool="modify_booking", ok=False, summary=str(exc), data={"error": "invalid_input"}
        )
    return ToolResult(
        tool="modify_booking",
        ok=True,
        summary=f"{resp.status.value}; fee ${resp.fee_applied:.0f} (waiver={resp.waiver_used}).",
        data=resp.model_dump(mode="json"),
    )


def escalate_to_human(args: EscalateArgs) -> ToolResult:
    """Signal a human handoff (non-mutating: it records the reason, it does not act)."""
    return ToolResult(
        tool="escalate_to_human",
        ok=True,
        summary=f"Handing off to a human ({args.category}): {args.reason}",
        data={"category": args.category, "reason": args.reason},
    )
