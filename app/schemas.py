"""Pydantic request/response models for the mock Booking API (mirrors doc 12).

Three separate response models reflect the spec's three *disjoint* status vocabularies,
each with validators that reject illegal states (e.g. ``tech_eta_minutes`` set when the
booking is not ``en_route``).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from meridian.domain.booking import AppointmentWindow, CustomerInfo
from meridian.domain.enums import (
    CancelReason,
    Channel,
    CreateStatus,
    JobType,
    LookupStatus,
    ModifyAction,
    ModifyStatus,
    ServiceType,
    Window,
)


class CreateBookingRequest(BaseModel):
    """Body for ``POST /bookings``."""

    customer_id: str | None = None
    customer_info: CustomerInfo | None = None
    service_type: ServiceType
    job_type: JobType
    zip_code: str = Field(pattern=r"^\d{5}$", description="5-digit ZIP of the service address.")
    preferred_date: date
    preferred_window: Window
    preferred_tech: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    channel: Channel

    @model_validator(mode="after")
    def _identity_required(self) -> CreateBookingRequest:
        if self.customer_id is None and self.customer_info is None:
            raise ValueError("Provide customer_id, or customer_info when customer_id is null.")
        return self


class CreateBookingResponse(BaseModel):
    """Response for ``POST /bookings``."""

    booking_id: str
    status: CreateStatus
    assigned_branch: str | None = None
    appointment_window: AppointmentWindow | None = None
    tech_name: str | None = None
    confirmation_sent: bool = False


class LookupResponse(BaseModel):
    """Response for ``GET /bookings/{id}`` (distinct status set from create/modify)."""

    booking_id: str
    status: LookupStatus
    service_type: ServiceType
    job_type: JobType
    appointment_window: AppointmentWindow
    tech_name: str | None = None
    tech_eta_minutes: int | None = None
    notes: str | None = None
    invoice_total: float | None = None

    @model_validator(mode="after")
    def _conditional_nullability(self) -> LookupResponse:
        if self.status is not LookupStatus.EN_ROUTE and self.tech_eta_minutes is not None:
            raise ValueError("tech_eta_minutes is only valid when status == en_route.")
        if self.status is not LookupStatus.COMPLETED and self.invoice_total is not None:
            raise ValueError("invoice_total is only valid when status == completed.")
        return self


class ModifyRequest(BaseModel):
    """Body for ``PATCH /bookings/{id}``."""

    action: ModifyAction
    new_date: date | None = None
    new_window: Window | None = None
    cancel_reason: CancelReason | None = None
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _reschedule_requires_slot(self) -> ModifyRequest:
        if self.action is ModifyAction.RESCHEDULE and (
            self.new_date is None or self.new_window is None
        ):
            raise ValueError("reschedule requires both new_date and new_window.")
        return self


class ModifyResponse(BaseModel):
    """Response for ``PATCH /bookings/{id}``."""

    booking_id: str
    status: ModifyStatus
    fee_applied: float = 0.0
    waiver_used: bool = False
    new_appointment_window: AppointmentWindow | None = None

    @model_validator(mode="after")
    def _window_matches_status(self) -> ModifyResponse:
        if self.status is ModifyStatus.RESCHEDULED and self.new_appointment_window is None:
            raise ValueError("a rescheduled response must include new_appointment_window.")
        if self.status is ModifyStatus.CANCELLED and self.new_appointment_window is not None:
            raise ValueError("a cancelled response must not include new_appointment_window.")
        return self
