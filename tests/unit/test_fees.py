"""Unit tests for quote-time computed fees (surcharge, diagnostic, emergency)."""

from __future__ import annotations

from datetime import date, datetime

from meridian.clock import EASTERN
from meridian.domain.enums import JobType, ServiceType
from meridian.knowledge.fees import (
    after_hours_surcharge,
    diagnostic_fee,
    emergency_dispatch_fee,
    is_federal_holiday,
)


def _dt(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=EASTERN)


def test_after_hours_surcharge() -> None:
    assert after_hours_surcharge(_dt(2026, 1, 18, 10)) == 125  # Sunday
    assert after_hours_surcharge(_dt(2026, 1, 20, 20)) == 75  # weekday after 6pm
    assert after_hours_surcharge(_dt(2026, 1, 20, 6)) == 75  # weekday before 7am
    assert after_hours_surcharge(_dt(2026, 1, 20, 10)) == 0  # weekday business hours
    assert after_hours_surcharge(_dt(2026, 7, 4, 10)) == 125  # federal holiday


def test_diagnostic_fee() -> None:
    assert diagnostic_fee(ServiceType.HVAC, JobType.DIAGNOSTIC) == 89
    assert diagnostic_fee(ServiceType.HVAC, JobType.REPAIR, same_day_repair_booked=True) == 0
    assert diagnostic_fee(ServiceType.ELECTRICAL, JobType.DIAGNOSTIC) == 85
    assert diagnostic_fee(ServiceType.PLUMBING, JobType.DIAGNOSTIC) == 75
    # warranty_return carries no diagnostic fee, for any service line
    assert diagnostic_fee(ServiceType.HVAC, JobType.WARRANTY_RETURN) == 0
    assert diagnostic_fee(ServiceType.PLUMBING, JobType.WARRANTY_RETURN) == 0


def test_emergency_dispatch_fee() -> None:
    # faq_emergencies documents emergency dispatch fees of $99 plumbing and $89 HVAC.
    assert emergency_dispatch_fee(ServiceType.PLUMBING) == 99
    assert emergency_dispatch_fee(ServiceType.HVAC) == 89
    assert emergency_dispatch_fee(ServiceType.ELECTRICAL) == 0  # none documented


def test_is_federal_holiday() -> None:
    assert is_federal_holiday(date(2026, 12, 25)) is True
    assert is_federal_holiday(date(2026, 3, 3)) is False
