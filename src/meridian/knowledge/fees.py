"""Quote-time computed fees (structured, never RAG).

Pricing *bands* (e.g. a 40-gal water heater is $950-$1,400) are answered via RAG with
citations. Fees that depend on inputs — day/time-of-week surcharges, the warranty
diagnostic-fee waiver — are computed here so the number is always exact and testable. All fee
VALUES come from the COMPILED fee schedule (:mod:`meridian.extraction`); federal holidays come
from the API-contract module. This module holds only the logic. (Cancellation/no-show fees are
enforced separately by the Booking API service.)
"""

from __future__ import annotations

from datetime import date, datetime

from ..api_contract import federal_holidays
from ..domain.enums import JobType, ServiceType
from .loader import load_fees

_SUNDAY = 6  # date.weekday() value for Sunday


def is_federal_holiday(day: date) -> bool:
    """Return True if ``day`` is a (modelled) US federal holiday."""
    return day in federal_holidays()


def after_hours_surcharge(when: datetime) -> int:
    """Return the after-hours surcharge in USD for an appointment at ``when``.

    Sunday or a federal holiday → the Sunday/holiday surcharge; Mon-Sat before the
    business-hours start or at/after the end → the weekday after-hours surcharge; else 0.
    """
    fees = load_fees()
    if when.weekday() == _SUNDAY or is_federal_holiday(when.date()):
        return fees.sunday_holiday_usd
    if when.hour < fees.business_hours_start_hour or when.hour >= fees.business_hours_end_hour:
        return fees.weekday_after_hours_usd
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
    """
    if job_type is JobType.WARRANTY_RETURN:
        return 0
    if service_type is ServiceType.HVAC and same_day_repair_booked:
        return 0
    return load_fees().diagnostic_fees_usd[service_type.value]


def emergency_dispatch_fee(service_type: ServiceType) -> int:
    """Return the emergency dispatch fee in USD (only plumbing documents one)."""
    return load_fees().emergency_dispatch_fees_usd.get(service_type.value, 0)
