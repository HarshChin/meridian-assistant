"""Pydantic argument schemas for each tool (the JSON schema the LLM fills in).

Validation happens in the registry before a handler runs, so a handler always receives a
well-formed, typed argument object — and a malformed LLM tool call surfaces as a typed
:class:`InvalidInputError`, never a crash.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..domain.booking import CustomerInfo
from ..domain.enums import CancelReason, JobType, ServiceType, Window


class KnowledgeSearchArgs(BaseModel):
    """Arguments for ``knowledge_search``."""

    query: str = Field(description="The customer's question, to search the knowledge base for.")


class CheckServiceAreaArgs(BaseModel):
    """Arguments for ``check_service_area``."""

    zip_code: str = Field(description="5-digit ZIP of the service address.")
    service_type: ServiceType = Field(description="The requested service line.")


class QuoteFeeArgs(BaseModel):
    """Arguments for ``quote_fee`` (one of several computed-fee kinds)."""

    kind: Literal["diagnostic", "emergency_dispatch", "cancellation", "after_hours_surcharge"] = (
        Field(description="Which fee to compute.")
    )
    service_type: ServiceType | None = Field(
        default=None, description="Required for 'diagnostic' and 'emergency_dispatch'."
    )
    job_type: JobType | None = Field(
        default=None, description="Job type for a 'diagnostic' quote (a warranty_return waives it)."
    )
    same_day_repair_booked: bool = Field(
        default=False, description="HVAC diagnostic is waived if a repair is booked the same day."
    )
    notice_hours: float | None = Field(
        default=None,
        description="Hours of notice before the appointment for a 'cancellation' quote "
        "(negative = no-show).",
    )
    appointment_datetime: datetime | None = Field(
        default=None,
        description="Appointment start for an 'after_hours_surcharge' quote (ISO 8601).",
    )


class LookupBookingArgs(BaseModel):
    """Arguments for ``lookup_booking``."""

    booking_id: str = Field(description="The booking id, e.g. BK-00391042.")
    customer_id: str | None = Field(
        default=None, description="Provide to unlock PII-gated fields (ownership check)."
    )


class CreateBookingArgs(BaseModel):
    """Arguments for ``create_booking`` (the inbound channel is supplied by the runner)."""

    service_type: ServiceType
    job_type: JobType
    zip_code: str = Field(pattern=r"^\d{5}$", description="5-digit ZIP of the service address.")
    preferred_date: date = Field(description="Requested date (resolved in code, never guessed).")
    preferred_window: Window
    customer_id: str | None = None
    customer_info: CustomerInfo | None = Field(
        default=None, description="Contact details when customer_id is unknown."
    )
    notes: str | None = Field(default=None, max_length=500)


class ModifyBookingArgs(BaseModel):
    """Arguments for ``modify_booking`` (reschedule / cancel)."""

    booking_id: str
    action: Literal["reschedule", "cancel"] = Field(
        description="Only reschedule and cancel are supported (update_notes is out of scope)."
    )
    new_date: date | None = Field(default=None, description="Required for a reschedule.")
    new_window: Window | None = Field(default=None, description="Required for a reschedule.")
    cancel_reason: CancelReason | None = None
    notes: str | None = Field(default=None, max_length=500)


class EscalateArgs(BaseModel):
    """Arguments for ``escalate_to_human``."""

    category: Literal[
        "emergency", "out_of_scope", "low_confidence", "missing_info", "fee_dispute", "other"
    ] = Field(description="Why the conversation is being handed off.")
    reason: str = Field(description="Short explanation shown to the human agent.")
