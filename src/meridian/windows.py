"""Appointment-window math and deterministic relative-date resolution.

Window time bands and the booking horizon are loaded from ``data/policy.yaml`` (sourced
from the API spec, doc 12); this module holds only the logic. Nothing here reads the wall
clock — callers pass ``now``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from .domain.booking import AppointmentWindow
from .domain.enums import Window
from .policy import get_policy

SUNDAY = 6
"""Python ``date.weekday()`` value for Sunday (Mon=0 … Sun=6)."""

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_hhmm(value: str) -> time:
    """Parse an ``"HH:MM"`` string into a :class:`datetime.time`."""
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@functools.lru_cache(maxsize=1)
def _bands() -> dict[Window, tuple[time, time]]:
    """Build the window → time-band map from policy data."""
    return {
        Window(name): (_parse_hhmm(start), _parse_hhmm(end))
        for name, (start, end) in get_policy().booking.windows.items()
    }


def band_for(window: Window) -> tuple[time, time]:
    """Return the ``(start, end)`` band for a concrete window.

    Raises:
        KeyError: if ``window`` is ``FIRST_AVAILABLE`` — resolve it first.
    """
    return _bands()[window]


def appointment_window(window: Window, day: date) -> AppointmentWindow:
    """Build a concrete :class:`AppointmentWindow` for ``window`` on ``day``."""
    start, end = band_for(window)
    return AppointmentWindow(
        date=day,
        start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M"),
    )


def within_advance_window(target: date, now: datetime, max_days: int | None = None) -> bool:
    """Return True if ``target`` is within today..now+``max_days`` (policy default) inclusive."""
    limit = max_days if max_days is not None else get_policy().booking.max_advance_days
    today = now.date()
    return today <= target <= today + timedelta(days=limit)


def resolve_relative_date(text: str, now: datetime) -> date | None:
    """Resolve a date phrase against ``now``; return ``None`` if ambiguous/absent.

    Handles ISO dates, "today", "tomorrow", weekday names ("next Wednesday" /
    "Wednesday"), and "the Nth". Deliberately returns ``None`` for vague phrases such as
    "next week" so the agent asks a clarifying question instead of guessing a date.
    """
    s = text.lower()
    today = now.date()

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    if "today" in s:
        return today
    if "tomorrow" in s:
        return today + timedelta(days=1)

    for name, idx in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", s):
            delta = (idx - today.weekday()) % 7 or 7  # always strictly future
            return today + timedelta(days=delta)

    dom = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)?\b", s)
    if dom:
        return _next_date_with_dom(int(dom.group(1)), today)

    return None


def _next_date_with_dom(dom: int, today: date) -> date | None:
    """Return the next date (>= ``today``) whose day-of-month equals ``dom``."""
    if not 1 <= dom <= 31:
        return None
    for offset in range(3):
        year = today.year + (today.month - 1 + offset) // 12
        month = (today.month - 1 + offset) % 12 + 1
        try:
            candidate = date(year, month, dom)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _open_except_sunday(day: date) -> bool:
    """Default openness predicate: open any day except Sunday."""
    return day.weekday() != SUNDAY


def resolve_first_available(
    now: datetime,
    is_open: Callable[[date], bool] | None = None,
    window: Window = Window.MORNING,
) -> AppointmentWindow:
    """Resolve ``first_available`` to the next open day's window, deterministically.

    Starts from *tomorrow* (member-tier same-day cutoffs are out of scope — see
    ASSUMPTIONS) and advances to the first day the branch is open.
    """
    predicate = is_open or _open_except_sunday
    day = now.date() + timedelta(days=1)
    for _ in range(get_policy().booking.max_advance_days):
        if predicate(day):
            return appointment_window(window, day)
        day += timedelta(days=1)
    return appointment_window(window, now.date() + timedelta(days=1))
