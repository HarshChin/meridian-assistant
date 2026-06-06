"""Shared pytest fixtures (frozen clock at the canonical instant)."""

from __future__ import annotations

import pytest

from meridian.clock import CANONICAL_NOW, FrozenClock


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """A clock pinned to the canonical instant for deterministic tests."""
    return FrozenClock(CANONICAL_NOW)
