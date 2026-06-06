"""Unit tests for the branch directory + hours."""

from __future__ import annotations

from datetime import date

from meridian.knowledge import branches

# 2026-01-24 is a Saturday; 2026-01-25 a Sunday; 2026-01-26 a Monday.
SATURDAY = date(2026, 1, 24)
SUNDAY = date(2026, 1, 25)
MONDAY = date(2026, 1, 26)


def test_emergency_line() -> None:
    assert branches.emergency_line() == "1-800-555-0190"


def test_eleven_branches_three_regions() -> None:
    rows = branches.list_branches()
    assert len(rows) == 11
    regions = {b["region"] for b in rows}
    assert regions == {"north", "central", "south"}


def test_college_park_closed_saturday() -> None:
    assert branches.is_open("College Park", SATURDAY) is False
    assert branches.is_open("College Park", MONDAY) is True


def test_sunday_emergency_is_not_open_for_normal_booking() -> None:
    # Falls Church is "emergency" on Sunday -> not open for a normal booking.
    assert branches.hours_on("Falls Church", SUNDAY) == "emergency"
    assert branches.is_open("Falls Church", SUNDAY) is False


def test_unknown_branch() -> None:
    assert branches.get_branch("Nowhere") is None
    assert branches.is_open("Nowhere", MONDAY) is False
