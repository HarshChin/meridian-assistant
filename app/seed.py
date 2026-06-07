"""Deterministic seed bookings for the mock Booking API.

Dates are anchored RELATIVE to a reference instant (``now``), so the same fixtures stay coherent
under any clock: the eval/tests use the canonical 2026-01-20 (reproducing the original January
dates exactly), while the CLI/web demo passes its own clock (e.g. 2026-05-01) and gets matching
dates. The set covers the spec example plus the booking IDs the eval references (status / ETA /
reschedule / PII-ownership / waiver scenarios).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from meridian.clock import CANONICAL_NOW
from meridian.domain.booking import AppointmentWindow
from meridian.domain.enums import JobType, LookupStatus, ServiceType

from .store import BookingRecord, BookingStore


def _window(day: date, start: str, end: str) -> AppointmentWindow:
    return AppointmentWindow(date=day, start_time=start, end_time=end)


def build_seed_store(now: datetime | None = None) -> BookingStore:
    """Build a freshly-seeded :class:`BookingStore`, dated relative to ``now`` (default Jan 20)."""
    base = (now or CANONICAL_NOW).date()

    def day(offset: int) -> date:
        return base + timedelta(days=offset)

    store = BookingStore()
    records = [
        # #4 status check — appointment "tomorrow"
        BookingRecord(
            booking_id="BK-00391042",
            owner_id="CID-1001",
            service_type=ServiceType.HVAC,
            job_type=JobType.DIAGNOSTIC,
            zip_code="22032",
            appointment_window=_window(day(1), "11:00", "14:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Dana Reyes",
            notes="AC intermittently not cooling.",
        ),
        # API spec example; #20 references tech "Marcus Webb"
        BookingRecord(
            booking_id="BK-00483921",
            owner_id="CID-1002",
            service_type=ServiceType.PLUMBING,
            job_type=JobType.REPAIR,
            zip_code="22032",
            appointment_window=_window(day(1), "10:00", "12:00"),
            status=LookupStatus.CONFIRMED,
            channel="web_chat",
            assigned_branch="Falls Church",
            tech_name="Marcus Webb",
        ),
        # #13 tech ETA — en_route with an ETA
        BookingRecord(
            booking_id="BK-00512883",
            owner_id="CID-1003",
            service_type=ServiceType.HVAC,
            job_type=JobType.DIAGNOSTIC,
            zip_code="22032",
            appointment_window=_window(day(0), "10:00", "12:00"),
            status=LookupStatus.EN_ROUTE,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Marcus Webb",
            tech_eta_minutes=12,
        ),
        # #13 else-branch sibling — confirmed (not en_route)
        BookingRecord(
            booking_id="BK-00512884",
            owner_id="CID-1003",
            service_type=ServiceType.HVAC,
            job_type=JobType.TUNE_UP,
            zip_code="22032",
            appointment_window=_window(day(0), "14:00", "18:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Priya Shah",
        ),
        # #5 reschedule target on the 22nd (>24h from canonical now -> no fee)
        BookingRecord(
            booking_id="BK-00400022",
            owner_id="CID-1004",
            service_type=ServiceType.HVAC,
            job_type=JobType.TUNE_UP,
            zip_code="22032",
            appointment_window=_window(day(2), "11:00", "14:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Dana Reyes",
        ),
        # seed-017 same-day 2pm, waiver AVAILABLE -> a <2h reschedule waives the $75
        BookingRecord(
            booking_id="BK-00477700",
            owner_id="CID-1010",
            service_type=ServiceType.PLUMBING,
            job_type=JobType.REPAIR,
            zip_code="22032",
            appointment_window=_window(day(0), "14:00", "18:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Luis Ortega",
        ),
        # ext-017 same-day 2pm, waiver ALREADY USED -> $75 applies
        BookingRecord(
            booking_id="BK-00477777",
            owner_id="CID-1005",
            service_type=ServiceType.PLUMBING,
            job_type=JobType.REPAIR,
            zip_code="22032",
            appointment_window=_window(day(0), "14:00", "18:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Sam Whitfield",
        ),
        # ext-014 PII ownership mismatch on GET
        BookingRecord(
            booking_id="BK-00399999",
            owner_id="CID-1000",
            service_type=ServiceType.ELECTRICAL,
            job_type=JobType.DIAGNOSTIC,
            zip_code="20814",
            appointment_window=_window(day(3), "11:00", "14:00"),
            status=LookupStatus.CONFIRMED,
            channel="agent",
            assigned_branch="Rockville",
            tech_name="Dana Reyes",
            notes="Panel inspection — PII gated behind ownership.",
        ),
        # completed booking with an invoice (PII-gated)
        BookingRecord(
            booking_id="BK-00388000",
            owner_id="CID-1006",
            service_type=ServiceType.PLUMBING,
            job_type=JobType.REPAIR,
            zip_code="22032",
            appointment_window=_window(day(-5), "10:00", "12:00"),
            status=LookupStatus.COMPLETED,
            channel="agent",
            assigned_branch="Falls Church",
            tech_name="Marcus Webb",
            invoice_total=275.0,
        ),
    ]
    for record in records:
        store.put(record)
    store.set_waiver("CID-1005", available=False)  # ext-017: waiver already consumed
    return store
