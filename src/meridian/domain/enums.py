"""Canonical enumerations mirroring the Booking API spec (doc 12) exactly.

The three booking *status* vocabularies are **disjoint** in the spec, so they are
modelled as separate enums (a single union would accept illegal states such as
``rescheduled`` on a create response). Coverage eligibility is a fourth, unrelated
vocabulary.
"""

from __future__ import annotations

from enum import StrEnum


class ServiceType(StrEnum):
    """Lines of service Meridian offers."""

    HVAC = "hvac"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"


class JobType(StrEnum):
    """Kind of job booked."""

    DIAGNOSTIC = "diagnostic"
    REPAIR = "repair"
    INSTALL = "install"
    TUNE_UP = "tune_up"
    WARRANTY_RETURN = "warranty_return"
    ESTIMATE = "estimate"


class Window(StrEnum):
    """Customer-preferred appointment window (maps to a time band in ``windows``)."""

    MORNING = "morning"
    MIDDAY = "midday"
    AFTERNOON = "afternoon"
    FIRST_AVAILABLE = "first_available"


class Channel(StrEnum):
    """Inbound channel; bearer tokens are scoped per channel."""

    IVR = "ivr"
    WEB_CHAT = "web_chat"
    EMAIL = "email"
    AGENT = "agent"


class CreateStatus(StrEnum):
    """Status returned by ``POST /bookings``."""

    CONFIRMED = "confirmed"
    PENDING_AVAILABILITY = "pending_availability"
    OUT_OF_AREA = "out_of_area"


class LookupStatus(StrEnum):
    """Status returned by ``GET /bookings/{id}`` (distinct from create/modify)."""

    CONFIRMED = "confirmed"
    EN_ROUTE = "en_route"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ModifyStatus(StrEnum):
    """Status returned by ``PATCH /bookings/{id}``."""

    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"


class ModifyAction(StrEnum):
    """``action`` field accepted by ``PATCH /bookings/{id}``."""

    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    UPDATE_NOTES = "update_notes"


class CancelReason(StrEnum):
    """Reason codes accepted on cancellation."""

    CUSTOMER_REQUEST = "customer_request"
    TECH_UNAVAILABLE = "tech_unavailable"
    WEATHER = "weather"
    DUPLICATE = "duplicate"
    OTHER = "other"


class CoverageEligibility(StrEnum):
    """Outcome of a service-area eligibility check.

    ``UNKNOWN`` (no coverage document, e.g. the South region) is deliberately
    distinct from ``NO`` (documented as not served) — they drive different responses.
    """

    YES = "yes"
    PENDING = "pending"
    NO = "no"
    UNKNOWN = "unknown"


class Region(StrEnum):
    """Operating regions."""

    NORTH = "north"
    CENTRAL = "central"
    SOUTH = "south"
