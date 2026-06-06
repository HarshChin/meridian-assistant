"""Appointment-window math and deterministic relative-date resolution.

Single source of truth for the window↔time-band mapping (we follow the Booking API
spec's bands, *not* the FAQ's "2-hour" prose — see ASSUMPTIONS #3) and for turning
phrases like "tomorrow" / "next Wednesday" / "the 24th" into concrete dates against an
injected clock. Nothing here reads the wall clock; callers pass ``now``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from .domain.booking import AppointmentWindow
from .domain.enums import Window

WINDOW_BANDS: dict[Window, tuple[time, time]] = {
    Window.MORNING: (time(7, 0), time(11, 0)),
    Window.MIDDAY: (time(11, 0), time(14, 0)),
    Window.AFTERNOON: (time(14, 0), time(18, 0)),
}
"""Window → (start, end) bands, transcribed from the API spec (doc 12)."""

MAX_ADVANCE_DAYS = 60
"""Bookings must be within 60 days of now (doc 12)."""

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def band_for(window: Window) -> tuple[time, time]:
    """Return the ``(start, end)`` time band for a concrete window.

    Args:
        window: A concrete window (not ``FIRST_AVAILABLE``).

    Raises:
        KeyError: if ``window`` is ``FIRST_AVAILABLE`` — resolve it first.
    """
    return WINDOW_BANDS[window]


def appointment_window(window: Window, day: date) -> AppointmentWindow:
    """Build a concrete :class:`AppointmentWindow` for ``window`` on ``day``."""
    start, end = band_for(window)
    return AppointmentWindow(
        date=day,
        start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M"),
    )


def within_advance_window(target: date, now: datetime, max_days: int = MAX_ADVANCE_DAYS) -> bool:
    """Return True if ``target`` falls within today..now+``max_days`` (inclusive)."""
    today = now.date()
    return today <= target <= today + timedelta(days=max_days)


def resolve_relative_date(text: str, now: datetime) -> date | None:
    """Resolve a date phrase against ``now``; return ``None`` if ambiguous/absent.

    Handles ISO dates, "today", "tomorrow", weekday names ("next Wednesday" /
    "Wednesday"), and "the Nth". Deliberately returns ``None`` for vague phrases such
    as "next week" so the agent asks a clarifying question instead of guessing a date.

    Args:
        text: Free text that may contain a date reference.
        now: Reference instant (injected clock).

    Returns:
        A resolved :class:`datetime.date`, or ``None`` if none is unambiguous.
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
    return day.weekday() != 6


def resolve_first_available(
    now: datetime,
    is_open: Callable[[date], bool] | None = None,
    window: Window = Window.MORNING,
) -> AppointmentWindow:
    """Resolve ``first_available`` to the next open day's window, deterministically.

    Starts from *tomorrow* (member-tier same-day cutoffs are out of scope — see
    ASSUMPTIONS) and advances to the first day the branch is open.

    Args:
        now: Reference instant (injected clock).
        is_open: Predicate for whether the branch operates on a date. Defaults to
            "open any day except Sunday".
        window: Window to schedule on the chosen day (default morning).

    Returns:
        A concrete :class:`AppointmentWindow`.
    """
    predicate = is_open or _open_except_sunday
    day = now.date() + timedelta(days=1)
    for _ in range(MAX_ADVANCE_DAYS):
        if predicate(day):
            return appointment_window(window, day)
        day += timedelta(days=1)
    return appointment_window(window, now.date() + timedelta(days=1))
