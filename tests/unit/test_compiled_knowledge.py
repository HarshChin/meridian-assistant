"""Compiled knowledge records match the document-sourced expectations (keyless).

These records are produced from the corpus by ``meridian.extraction.compile`` and committed.
This test pins their values, so any drift in extraction (or a stale recompile) is caught by
the keyless gate. The API-contract constants (doc 12) are checked alongside.
"""

from __future__ import annotations

from datetime import date

from meridian.api_contract import MAX_ADVANCE_DAYS, WINDOW_BANDS, federal_holidays
from meridian.knowledge.loader import load_branches, load_fees


def test_fee_schedule_values() -> None:
    f = load_fees()
    assert (f.free_notice_hours, f.late_cancel_threshold_hours) == (24, 2)
    assert (f.late_cancel_fee_usd, f.no_show_fee_usd) == (35, 75)
    assert f.no_show_waiver_period_months == 12
    assert (f.weekday_after_hours_usd, f.sunday_holiday_usd) == (75, 125)
    assert (f.business_hours_start_hour, f.business_hours_end_hour) == (7, 18)
    assert f.diagnostic_fees_usd == {"hvac": 89, "electrical": 85, "plumbing": 75}
    # faq_emergencies documents "($99 plumbing, $89 HVAC)" — both are compiled (the old
    # hand-authored data missed the $89 HVAC figure; the grounded path captures it).
    assert f.emergency_dispatch_fees_usd == {"plumbing": 99, "hvac": 89}


def test_branch_directory() -> None:
    b = load_branches()
    assert b.emergency_line == "1-800-555-0190"
    assert len(b.branches) == 11
    assert {x.region for x in b.branches} == {"north", "central", "south"}


def test_api_contract_constants() -> None:
    assert WINDOW_BANDS["afternoon"] == ("14:00", "18:00")
    assert MAX_ADVANCE_DAYS == 60
    assert date(2026, 12, 25) in federal_holidays()
