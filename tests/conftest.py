"""Shared pytest fixtures (frozen clock, canonical instant)."""

from __future__ import annotations

from datetime import datetime

import pytest

from meridian.clock import EASTERN, FrozenClock

CANONICAL_NOW = datetime(2026, 1, 20, 9, 0, tzinfo=EASTERN)
"""Canonical demo/eval instant: Tue 2026-01-20 09:00 ET (see PLAN determinism)."""


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """A clock pinned to the canonical instant for deterministic tests."""
    return FrozenClock(CANONICAL_NOW)
