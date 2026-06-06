"""Policy values load from data/policy.yaml and match the doc-sourced expectations."""

from __future__ import annotations

from datetime import date

from meridian.policy import get_policy


def test_cancellation_policy_values() -> None:
    c = get_policy().cancellation
    assert (c.free_notice_hours, c.late_cancel_threshold_hours) == (24, 2)
    assert (c.late_cancel_fee_usd, c.no_show_fee_usd) == (35, 75)
    assert c.no_show_waiver_period_months == 12


def test_surcharge_and_diagnostic_and_emergency_values() -> None:
    p = get_policy()
    assert (p.surcharges.weekday_after_hours_usd, p.surcharges.sunday_holiday_usd) == (75, 125)
    assert (p.surcharges.business_hours_start_hour, p.surcharges.business_hours_end_hour) == (7, 18)
    assert p.diagnostic_fees_usd == {"hvac": 89, "electrical": 85, "plumbing": 75}
    assert p.emergency_dispatch_fees_usd == {"plumbing": 99}


def test_booking_windows_and_holidays() -> None:
    b = get_policy().booking
    assert b.max_advance_days == 60
    assert b.notes_max_length == 500
    assert b.windows["afternoon"] == ("14:00", "18:00")
    assert date(2026, 12, 25) in get_policy().federal_holidays
