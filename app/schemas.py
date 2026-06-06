"""Booking API request/response models.

The contract models now live in the shared library (:mod:`meridian.api_client.models`) so the
mock server and the typed client share one definition. This module re-exports them for the
server's existing imports.
"""

from __future__ import annotations

from meridian.api_client.models import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)

__all__ = [
    "CreateBookingRequest",
    "CreateBookingResponse",
    "LookupResponse",
    "ModifyRequest",
    "ModifyResponse",
]
