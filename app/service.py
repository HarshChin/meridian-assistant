"""BookingService — the single source of truth for booking business logic.

Wraps a :class:`BookingStore` with the doc-12 contract and the verified fee/window/
coverage rules. Fee VALUES come from the COMPILED fee schedule (``meridian.knowledge.loader``,
itself produced from the source documents by ``meridian.extraction``); this module holds the
deterministic logic that applies them. Used directly as the in-process double (tools + eval)
and behind the FastAPI app. All time-dependent logic uses the injected :class:`Clock` — never
the wall clock — so fees/windows are deterministic.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time

from meridian.api_contract import MAX_ADVANCE_DAYS
from meridian.clock import EASTERN, Clock
from meridian.domain.booking import AppointmentWindow
from meridian.domain.enums import (
    CoverageEligibility,
    CreateStatus,
    LookupStatus,
    ModifyAction,
    ModifyStatus,
    Window,
)
from meridian.domain.errors import BookingNotFoundError, InvalidInputError, OwnershipError
from meridian.knowledge import branches
from meridian.knowledge.coverage import check_coverage
from meridian.knowledge.fees import cancellation_fee
from meridian.knowledge.loader import load_fees
from meridian.windows import (
    SUNDAY,
    appointment_window,
    resolve_first_available,
    within_advance_window,
)

from .fixtures import load_technician_roster
from .schemas import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)
from .store import BookingRecord, BookingStore


class BookingService:
    """Business logic for creating, looking up, and modifying bookings."""

    def __init__(self, clock: Clock, store: BookingStore) -> None:
        """Initialise with an injected clock and store."""
        self._clock = clock
        self._store = store

    @property
    def store(self) -> BookingStore:
        """The underlying store (the eval inspects its mutation ledger)."""
        return self._store

    # --------------------------------------------------------------- create
    def create_booking(self, req: CreateBookingRequest) -> CreateBookingResponse:
        """Create a booking, gating on the 60-day window and service-area coverage."""
        now = self._clock.now()
        if not within_advance_window(req.preferred_date, now):
            raise InvalidInputError(
                f"preferred_date must be within {MAX_ADVANCE_DAYS} days (got {req.preferred_date})."
            )

        key = self._idempotency_key(req)
        existing_id = self._store.idempotency_get(key)
        if existing_id is not None:
            existing = self._store.get(existing_id)
            if existing is not None:
                return CreateBookingResponse(
                    booking_id=existing.booking_id,
                    status=CreateStatus.CONFIRMED,
                    assigned_branch=existing.assigned_branch,
                    appointment_window=existing.appointment_window,
                    tech_name=existing.tech_name,
                    confirmation_sent=True,
                )

        coverage = check_coverage(req.zip_code, req.service_type)
        if coverage.eligibility in (CoverageEligibility.NO, CoverageEligibility.UNKNOWN):
            return CreateBookingResponse(
                booking_id=self._store.next_booking_id(),
                status=CreateStatus.OUT_OF_AREA,
                confirmation_sent=False,
            )

        pending = coverage.eligibility is CoverageEligibility.PENDING
        status = CreateStatus.PENDING_AVAILABILITY if pending else CreateStatus.CONFIRMED
        window = self._resolve_window(
            req.preferred_window, req.preferred_date, coverage.primary_branch
        )
        booking_id = self._store.next_booking_id()
        tech = None if pending else self._assign_tech(booking_id)

        self._store.put(
            BookingRecord(
                booking_id=booking_id,
                owner_id=req.customer_id,
                service_type=req.service_type,
                job_type=req.job_type,
                zip_code=req.zip_code,
                appointment_window=window,
                status=LookupStatus.CONFIRMED,
                channel=req.channel.value,
                assigned_branch=coverage.primary_branch,
                tech_name=tech,
                notes=req.notes,
                customer_info=req.customer_info,
            )
        )
        self._store.idempotency_set(key, booking_id)
        self._store.record_mutation("create", booking_id)
        return CreateBookingResponse(
            booking_id=booking_id,
            status=status,
            assigned_branch=coverage.primary_branch,
            appointment_window=window,
            tech_name=tech,
            confirmation_sent=True,
        )

    # --------------------------------------------------------------- lookup
    def get_booking(self, booking_id: str, customer_id: str | None = None) -> LookupResponse:
        """Return a booking; gate PII fields on ownership when ``customer_id`` is given."""
        rec = self._store.get(booking_id)
        if rec is None:
            raise BookingNotFoundError(booking_id)
        if customer_id is not None and rec.owner_id is not None and customer_id != rec.owner_id:
            raise OwnershipError("Booking does not belong to the provided customer_id.")
        owns = customer_id is not None and customer_id == rec.owner_id
        completed = rec.status is LookupStatus.COMPLETED
        return LookupResponse(
            booking_id=rec.booking_id,
            status=rec.status,
            service_type=rec.service_type,
            job_type=rec.job_type,
            appointment_window=rec.appointment_window,
            tech_name=rec.tech_name,
            tech_eta_minutes=rec.tech_eta_minutes if rec.status is LookupStatus.EN_ROUTE else None,
            notes=rec.notes if owns else None,
            invoice_total=rec.invoice_total if (owns and completed) else None,
        )

    # --------------------------------------------------------------- modify
    def modify_booking(self, booking_id: str, req: ModifyRequest) -> ModifyResponse:
        """Dispatch a PATCH to reschedule or cancel (update_notes is out of scope)."""
        rec = self._store.get(booking_id)
        if rec is None:
            raise BookingNotFoundError(booking_id)
        if req.action is ModifyAction.RESCHEDULE:
            return self._reschedule(rec, req)
        if req.action is ModifyAction.CANCEL:
            return self._cancel(rec)
        raise InvalidInputError("The update_notes action is out of scope for this prototype.")

    def _reschedule(self, rec: BookingRecord, req: ModifyRequest) -> ModifyResponse:
        assert req.new_date is not None and req.new_window is not None  # enforced by the model
        now = self._clock.now()
        if not within_advance_window(req.new_date, now):
            raise InvalidInputError(
                f"new_date must be within {MAX_ADVANCE_DAYS} days (got {req.new_date})."
            )
        notice_hours = self._notice_hours(rec, now)
        fee, waiver_used = 0, False
        free_hours = load_fees().free_notice_hours
        # >free-notice is free; otherwise a same-day move is free, else it is a late-cancel.
        if notice_hours <= free_hours and req.new_date != now.date():
            fee, waiver_used = self._fee_with_waiver(rec.owner_id, notice_hours)
        window = self._resolve_window(req.new_window, req.new_date, rec.assigned_branch)
        rec.appointment_window = window
        rec.status = LookupStatus.CONFIRMED
        self._store.record_mutation("reschedule", rec.booking_id)
        return ModifyResponse(
            booking_id=rec.booking_id,
            status=ModifyStatus.RESCHEDULED,
            fee_applied=float(fee),
            waiver_used=waiver_used,
            new_appointment_window=window,
        )

    def _cancel(self, rec: BookingRecord) -> ModifyResponse:
        now = self._clock.now()
        fee, waiver_used = self._fee_with_waiver(rec.owner_id, self._notice_hours(rec, now))
        rec.status = LookupStatus.CANCELLED
        self._store.record_mutation("cancel", rec.booking_id)
        return ModifyResponse(
            booking_id=rec.booking_id,
            status=ModifyStatus.CANCELLED,
            fee_applied=float(fee),
            waiver_used=waiver_used,
        )

    # --------------------------------------------------------------- helpers
    def _fee_with_waiver(self, owner_id: str | None, notice_hours: float) -> tuple[int, bool]:
        """Compute the fee, applying the once-per-12-months no-show waiver if available."""
        base = cancellation_fee(notice_hours)
        if base == load_fees().no_show_fee_usd and self._store.waiver_available(owner_id):
            self._store.consume_waiver(owner_id)
            return 0, True
        return base, False

    def _notice_hours(self, rec: BookingRecord, now: datetime) -> float:
        """Hours between ``now`` and the booking's appointment start."""
        parts = rec.appointment_window.start_time.split(":")
        appt = datetime.combine(
            rec.appointment_window.date, time(int(parts[0]), int(parts[1])), tzinfo=EASTERN
        )
        return (appt - now).total_seconds() / 3600.0

    def _resolve_window(self, window: Window, day: date, branch: str | None) -> AppointmentWindow:
        """Resolve a preferred window to a concrete :class:`AppointmentWindow`."""
        if window is Window.FIRST_AVAILABLE:

            def _open(candidate: date) -> bool:
                if branch:
                    return branches.is_open(branch, candidate)
                return candidate.weekday() != SUNDAY

            return resolve_first_available(self._clock.now(), is_open=_open)
        return appointment_window(window, day)

    def _assign_tech(self, booking_id: str) -> str:
        """Deterministically assign a technician from the mock roster fixture."""
        roster = load_technician_roster()
        ordinal = int(booking_id.rsplit("-", 1)[-1])
        return roster[ordinal % len(roster)]

    def _idempotency_key(self, req: CreateBookingRequest) -> str:
        """Stable key to dedupe identical create requests (closes the double-confirm race)."""
        cust = req.customer_id or (req.customer_info.phone if req.customer_info else "anon")
        raw = "|".join(
            [
                str(cust),
                req.service_type.value,
                req.job_type.value,
                req.zip_code,
                req.preferred_date.isoformat(),
                req.preferred_window.value,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
