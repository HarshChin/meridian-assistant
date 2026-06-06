"""Mock Booking API (FastAPI) + the in-process BookingService it wraps.

``app.service.BookingService`` is the single source of truth for booking business
logic; it is used directly as the in-process double (tools/eval) and behind the
FastAPI HTTP app in ``app.main``.
"""
