"""Booking API contract constants (doc 12) + a documented federal-holiday stub.

These are deliberately NOT compiled from the knowledge corpus. They are part of the Booking
API specification we *implement* — ``12_booking_api_spec.pdf`` is intentionally excluded from
the RAG corpus because it is the system contract, not retrievable customer knowledge — plus a
small federal-holiday simplification (see ASSUMPTIONS.md). Unlike business facts, they do not
change as the document corpus grows, so they live in code with explicit provenance.
"""

from __future__ import annotations

from datetime import date

# --- Appointment-window bands (source: 12_booking_api_spec.pdf) -----------------------
WINDOW_BANDS: dict[str, tuple[str, str]] = {
    "morning": ("07:00", "11:00"),
    "midday": ("11:00", "14:00"),
    "afternoon": ("14:00", "18:00"),
}
"""Preferred-window → ``(start, end)`` time band, per the Booking API spec."""

MAX_ADVANCE_DAYS = 60
"""Bookings may be made at most this many days ahead (Booking API spec / faq_booking)."""

NOTES_MAX_LENGTH = 500
"""Maximum length of the free-text ``notes`` field (Booking API spec)."""

# --- Federal holidays (documented simplification; see ASSUMPTIONS.md) -----------------
_FEDERAL_HOLIDAYS_2026: tuple[date, ...] = (
    date(2026, 1, 1),  # New Year's Day
    date(2026, 1, 19),  # MLK Jr. Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 4),  # Independence Day
    date(2026, 9, 7),  # Labor Day
    date(2026, 10, 12),  # Columbus Day
    date(2026, 11, 11),  # Veterans Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
)


def federal_holidays() -> frozenset[date]:
    """Return the modelled US federal-holiday set (a documented prototype simplification)."""
    return frozenset(_FEDERAL_HOLIDAYS_2026)
