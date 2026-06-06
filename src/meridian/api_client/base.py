"""The :class:`BookingClient` Protocol — the seam between the agent and the Booking API.

Both the in-process ``BookingService`` (used by the tools / eval) and :class:`HttpBookingClient`
(used by the web demo) satisfy this Protocol, so the agent depends only on the seam and is
indifferent to transport.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)


@runtime_checkable
class BookingClient(Protocol):
    """Transport-agnostic Booking API surface (create / lookup / modify)."""

    def create_booking(self, req: CreateBookingRequest) -> CreateBookingResponse:
        """Create a booking."""
        ...

    def get_booking(self, booking_id: str, customer_id: str | None = None) -> LookupResponse:
        """Look up a booking; PII fields are gated on ``customer_id`` ownership."""
        ...

    def modify_booking(self, booking_id: str, req: ModifyRequest) -> ModifyResponse:
        """Reschedule or cancel a booking."""
        ...
