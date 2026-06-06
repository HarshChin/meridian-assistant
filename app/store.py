"""In-memory booking store: records, a mutation ledger, waiver + idempotency state.

The **mutation ledger** is the eval's independent ground truth: it records every
state-changing operation, so the harness can prove no booking was created/modified
before an explicit confirmation (rather than trusting the agent's self-reported trace).
"""

from __future__ import annotations

from dataclasses import dataclass

from meridian.domain.booking import AppointmentWindow, CustomerInfo
from meridian.domain.enums import JobType, LookupStatus, ServiceType

_ID_SEED = 90_000_000  # generated ids start at BK-90000001; well clear of seeded ids


@dataclass
class BookingRecord:
    """Internal booking state (superset of the API response fields)."""

    booking_id: str
    owner_id: str | None
    service_type: ServiceType
    job_type: JobType
    zip_code: str
    appointment_window: AppointmentWindow
    status: LookupStatus
    channel: str
    assigned_branch: str | None = None
    tech_name: str | None = None
    tech_eta_minutes: int | None = None
    notes: str | None = None
    invoice_total: float | None = None
    customer_info: CustomerInfo | None = None


@dataclass
class MutationEvent:
    """A single state-changing operation, recorded in sequence."""

    seq: int
    op: str  # "create" | "reschedule" | "cancel" | "update_notes"
    booking_id: str


class BookingStore:
    """Mutable in-memory state for the mock Booking API."""

    def __init__(self) -> None:
        """Initialise an empty store."""
        self._bookings: dict[str, BookingRecord] = {}
        self._waiver_available: dict[str, bool] = {}
        self._idempotency: dict[str, str] = {}
        self._mutations: list[MutationEvent] = []
        self._id_counter = _ID_SEED

    # --- bookings ---
    def get(self, booking_id: str) -> BookingRecord | None:
        """Return the record for ``booking_id`` or ``None``."""
        return self._bookings.get(booking_id)

    def put(self, record: BookingRecord) -> None:
        """Insert or replace a booking record."""
        self._bookings[record.booking_id] = record

    def next_booking_id(self) -> str:
        """Return a fresh deterministic ``BK-XXXXXXXX`` id."""
        self._id_counter += 1
        return f"BK-{self._id_counter:08d}"

    # --- mutation ledger ---
    def record_mutation(self, op: str, booking_id: str) -> None:
        """Append a mutation event to the ledger."""
        self._mutations.append(
            MutationEvent(seq=len(self._mutations) + 1, op=op, booking_id=booking_id)
        )

    @property
    def mutations(self) -> list[MutationEvent]:
        """Return the ordered mutation ledger (read-only copy)."""
        return list(self._mutations)

    # --- waiver ledger (once-per-12-months no-show waiver, simplified to a flag) ---
    def waiver_available(self, customer_id: str | None) -> bool:
        """Return True if the customer still has their no-show waiver (default True)."""
        if customer_id is None:
            return True  # unknown/first-time customer
        return self._waiver_available.get(customer_id, True)

    def consume_waiver(self, customer_id: str | None) -> None:
        """Mark the customer's no-show waiver as used."""
        if customer_id is not None:
            self._waiver_available[customer_id] = False

    def set_waiver(self, customer_id: str, available: bool) -> None:
        """Seed/override a customer's waiver availability."""
        self._waiver_available[customer_id] = available

    # --- idempotency ---
    def idempotency_get(self, key: str) -> str | None:
        """Return the booking id previously created for ``key`` (or ``None``)."""
        return self._idempotency.get(key)

    def idempotency_set(self, key: str, booking_id: str) -> None:
        """Associate an idempotency ``key`` with a created ``booking_id``."""
        self._idempotency[key] = booking_id
