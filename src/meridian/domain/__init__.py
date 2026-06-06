"""Pure domain types: enums, value objects, and errors (no I/O, no LLM)."""

from __future__ import annotations

from .booking import AppointmentWindow, CustomerInfo
from .enums import (
    CancelReason,
    Channel,
    CoverageEligibility,
    CreateStatus,
    JobType,
    LookupStatus,
    ModifyAction,
    ModifyStatus,
    Region,
    ServiceType,
    Window,
)
from .errors import (
    BookingNotFoundError,
    InvalidInputError,
    MeridianError,
    MutationOutsideCommitError,
    OutOfAreaError,
    OwnershipError,
)
from .service_area import CoverageDecision, CoverageFlags

__all__ = [
    "AppointmentWindow",
    "BookingNotFoundError",
    "CancelReason",
    "Channel",
    "CoverageDecision",
    "CoverageEligibility",
    "CoverageFlags",
    "CreateStatus",
    "CustomerInfo",
    "InvalidInputError",
    "JobType",
    "LookupStatus",
    "MeridianError",
    "ModifyAction",
    "ModifyStatus",
    "MutationOutsideCommitError",
    "OutOfAreaError",
    "OwnershipError",
    "Region",
    "ServiceType",
    "Window",
]
