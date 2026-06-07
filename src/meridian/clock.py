"""Time abstraction so business logic never reads the wall clock directly.

Fee tiers, the 60-day booking window, ``first_available`` resolution, and
relative-date parsing all depend on "now". Injecting a :class:`Clock` keeps those
deterministic and unit-testable: production wires :class:`SystemClock`; tests and
the eval harness wire :class:`FrozenClock`.

This module is the *only* place in ``src/meridian`` permitted to call
``datetime.now`` (enforced by a CI grep gate).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
"""Meridian operates in the US Eastern timezone (branch hours, surcharges)."""

CANONICAL_NOW = datetime(2026, 1, 20, 9, 0, tzinfo=EASTERN)
"""Canonical EVAL/test instant: Tue 2026-01-20 09:00 ET. Pins the deterministic, keyless eval."""

DEMO_NOW = datetime(2026, 5, 1, 9, 0, tzinfo=EASTERN)
"""Frozen instant for the interactive CLI/web demo: Fri 2026-05-01 09:00 ET, giving a bookable
window of 2026-05-01..2026-06-30 (the 60-day horizon). Kept separate from CANONICAL_NOW so the
eval/tests stay pinned at January; the seed is dated relative to whichever clock is used."""


@runtime_checkable
class Clock(Protocol):
    """A source of the current instant."""

    def now(self) -> datetime:
        """Return the current timezone-aware datetime."""
        ...


class SystemClock:
    """Real wall-clock time in the configured timezone."""

    def __init__(self, tz: ZoneInfo = EASTERN) -> None:
        """Initialise the clock.

        Args:
            tz: Timezone for returned instants.
        """
        self._tz = tz

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""
        return datetime.now(self._tz)


class FrozenClock:
    """A fixed clock that always returns the same instant (for determinism)."""

    def __init__(self, moment: datetime, tz: ZoneInfo = EASTERN) -> None:
        """Initialise the frozen clock.

        Args:
            moment: The instant :meth:`now` always returns. A naive ``moment`` is
                interpreted as being in ``tz``.
            tz: Timezone applied to a naive ``moment``.
        """
        self._moment = moment if moment.tzinfo is not None else moment.replace(tzinfo=tz)

    def now(self) -> datetime:
        """Return the frozen instant (timezone-aware)."""
        return self._moment
