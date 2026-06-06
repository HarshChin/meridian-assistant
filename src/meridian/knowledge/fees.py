"""Quote-time computed fees (structured, never RAG).

Pricing *bands* (e.g. a 40-gal water heater is $950-$1,400) are answered via RAG with
citations. Fees that depend on inputs — day/time-of-week surcharges, the warranty
diagnostic-fee waiver — are computed here so the number is always exact and testable.
(Cancellation/no-show fees are enforced separately by the Booking API service.)
"""

from __future__ import annotations

from datetime import date, datetime

from ..domain.enums import JobType, ServiceType

WEEKDAY_AFTER_HOURS_SURCHARGE = 75
"""+$75 for Mon-Sat calls before 7am or after 6pm (doc 03)."""

SUNDAY_HOLIDAY_SURCHARGE = 125
"""+$125 for Sunday / federal-holiday calls (doc 03)."""

# Base diagnostic / service-call fees by service line (doc 03/04/05).
DIAGNOSTIC_FEE = {
    ServiceType.HVAC: 89,
    ServiceType.ELECTRICAL: 85,
    ServiceType.PLUMBING: 75,
}

EMERGENCY_DISPATCH_FEE = {ServiceType.PLUMBING: 99}
"""Only plumbing documents an emergency dispatch fee ($99); not waived after-hours."""

# Minimal US federal-holiday set for 2026 (documented simplification — see ASSUMPTIONS).
US_FEDERAL_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
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
    }
)


def is_federal_holiday(day: date) -> bool:
    """Return True if ``day`` is a (modelled) 2026 US federal holiday."""
    return day in US_FEDERAL_HOLIDAYS_2026


def after_hours_surcharge(when: datetime) -> int:
    """Return the after-hours surcharge in USD for an appointment at ``when``.

    Sunday or a federal holiday → +$125; Mon-Sat before 7am or at/after 6pm → +$75;
    otherwise $0.

    Args:
        when: The appointment datetime (timezone-aware).

    Returns:
        Surcharge in whole USD.
    """
    if when.weekday() == 6 or is_federal_holiday(when.date()):
        return SUNDAY_HOLIDAY_SURCHARGE
    if when.hour < 7 or when.hour >= 18:
        return WEEKDAY_AFTER_HOURS_SURCHARGE
    return 0


def diagnostic_fee(
    service_type: ServiceType,
    job_type: JobType,
    *,
    same_day_repair_booked: bool = False,
) -> int:
    """Return the diagnostic / service-call fee in USD.

    Warranty visits carry no diagnostic fee; the HVAC diagnostic fee is waived when a
    repair is booked the same day. (Electrical/plumbing repair-total waivers depend on
    the final invoice and are out of scope for a phone quote — see ASSUMPTIONS.)

    Args:
        service_type: The service line.
        job_type: The job type (``warranty_return`` ⇒ no fee).
        same_day_repair_booked: True if an HVAC repair is booked the same day.

    Returns:
        The fee in whole USD (0 if waived).
    """
    if job_type is JobType.WARRANTY_RETURN:
        return 0
    if service_type is ServiceType.HVAC and same_day_repair_booked:
        return 0
    return DIAGNOSTIC_FEE[service_type]


def emergency_dispatch_fee(service_type: ServiceType) -> int:
    """Return the emergency dispatch fee in USD (only plumbing documents one: $99)."""
    return EMERGENCY_DISPATCH_FEE.get(service_type, 0)
