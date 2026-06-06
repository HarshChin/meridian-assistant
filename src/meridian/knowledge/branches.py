"""Branch directory + operating hours (from ``data/branches.yaml``)."""

from __future__ import annotations

import functools
from datetime import date
from typing import Any

import yaml

from ..config import get_settings

# weekday() 0..6 (Mon..Sun) → the YAML key holding that day's hours.
_DAY_KEYS: tuple[str, ...] = ("mon_fri", "mon_fri", "mon_fri", "mon_fri", "mon_fri", "sat", "sun")


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    """Load and cache the branch directory YAML."""
    path = get_settings().data_dir / "branches.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def emergency_line() -> str:
    """Return the 24/7 emergency phone number."""
    return str(_load()["emergency_line"])


def list_branches() -> list[dict[str, Any]]:
    """Return all branch records."""
    return list(_load()["branches"])


def get_branch(name: str) -> dict[str, Any] | None:
    """Return the branch record by name (case-insensitive), or ``None``."""
    for branch in _load()["branches"]:
        if branch["name"].lower() == name.lower():
            return branch
    return None


def hours_on(branch_name: str, day: date) -> str | None:
    """Return the hours string for a branch on ``day``, or ``None`` if unknown branch."""
    branch = get_branch(branch_name)
    if branch is None:
        return None
    return str(branch.get(_DAY_KEYS[day.weekday()], "closed"))


def is_open(branch_name: str, day: date) -> bool:
    """Return True if the branch takes normal bookings on ``day``.

    Sunday ``"emergency"`` and ``"closed"`` both count as not open for normal booking.
    """
    hours = hours_on(branch_name, day)
    return hours is not None and hours not in ("closed", "emergency")
