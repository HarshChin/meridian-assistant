"""Typed Booking API client: a :class:`BookingClient` Protocol + an HTTP implementation.

The in-process "double" is simply an :class:`~app.service.BookingService`, which satisfies the
:class:`BookingClient` Protocol structurally — so the tools / agent / eval can run against the
exact same business logic with no HTTP (fast, deterministic, keyless), while
:class:`HttpBookingClient` exercises the real wire contract (serialisation, auth, status codes).
"""

from .base import BookingClient
from .http import HttpBookingClient
from .models import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)

__all__ = [
    "BookingClient",
    "CreateBookingRequest",
    "CreateBookingResponse",
    "HttpBookingClient",
    "LookupResponse",
    "ModifyRequest",
    "ModifyResponse",
]
