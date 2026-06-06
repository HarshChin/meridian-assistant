"""Smoke tests: the package imports and the clock abstraction behaves."""

from __future__ import annotations

from datetime import datetime

from meridian import __version__
from meridian.clock import Clock, FrozenClock, SystemClock


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_frozen_clock_is_deterministic() -> None:
    clock = FrozenClock(datetime(2026, 1, 20, 9, 0))
    assert clock.now() == clock.now()
    assert clock.now().year == 2026
    assert clock.now().tzinfo is not None  # naive input is localised


def test_clocks_satisfy_protocol() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FrozenClock(datetime(2026, 1, 20)), Clock)
