"""Unit tests for window bands and deterministic relative-date resolution."""

from __future__ import annotations

from datetime import date, datetime

from meridian.clock import EASTERN
from meridian.domain.enums import Window
from meridian.windows import (
    appointment_window,
    band_for,
    resolve_first_available,
    resolve_relative_date,
    within_advance_window,
)

NOW = datetime(2026, 1, 20, 9, 0, tzinfo=EASTERN)  # Tuesday


def test_bands_follow_api_spec() -> None:
    assert band_for(Window.MORNING) == (
        datetime(2026, 1, 1, 7).time(),
        datetime(2026, 1, 1, 11).time(),
    )
    aw = appointment_window(Window.AFTERNOON, date(2026, 1, 24))
    assert (aw.start_time, aw.end_time) == ("14:00", "18:00")


def test_relative_dates() -> None:
    assert resolve_relative_date("can someone come today?", NOW) == date(2026, 1, 20)
    assert resolve_relative_date("tomorrow please", NOW) == date(2026, 1, 21)
    # NOW is Tuesday; "next Wednesday" -> the next day (Wed 21st)
    assert resolve_relative_date("next Wednesday morning", NOW) == date(2026, 1, 21)
    assert resolve_relative_date("move it to the 24th", NOW) == date(2026, 1, 24)
    assert resolve_relative_date("2026-01-22", NOW) == date(2026, 1, 22)


def test_absolute_month_name_dates() -> None:
    # Customers type explicit dates; a month NAME makes them unambiguous (no M/D vs D/M guessing).
    assert resolve_relative_date("on 12th jan 2026", NOW) == date(2026, 1, 12)
    assert resolve_relative_date("for 28th January 2026", NOW) == date(2026, 1, 28)
    assert resolve_relative_date("January 28 2026", NOW) == date(2026, 1, 28)
    assert resolve_relative_date("Feb 3rd, 2026", NOW) == date(2026, 2, 3)
    # No year given -> the next occurrence (this year if not past).
    assert resolve_relative_date("march 5", NOW) == date(2026, 3, 5)


def test_vague_dates_return_none_so_agent_clarifies() -> None:
    assert resolve_relative_date("sometime next week", NOW) is None
    assert resolve_relative_date("whenever works", NOW) is None
    assert resolve_relative_date("1/12/2026", NOW) is None  # numeric M/D is ambiguous -> clarify
    assert resolve_relative_date("book me in february", NOW) is None  # month, no day -> clarify


def test_advance_window() -> None:
    assert within_advance_window(date(2026, 2, 19), NOW) is True  # +30d
    assert within_advance_window(date(2026, 4, 30), NOW) is False  # >60d
    assert within_advance_window(date(2026, 1, 19), NOW) is False  # past


def test_first_available_skips_sunday_by_default() -> None:
    # From Tue 2026-01-20, tomorrow (Wed 21) is open by the default predicate.
    aw = resolve_first_available(NOW)
    assert aw.date == date(2026, 1, 21)
    assert (aw.start_time, aw.end_time) == ("07:00", "11:00")


def test_documented_date_conflict_friday_24th_is_actually_saturday() -> None:
    # ASSUMPTIONS #2: test #5 says "Friday the 24th" but 2026-01-24 is a Saturday.
    assert date(2026, 1, 24).weekday() == 5  # Saturday
