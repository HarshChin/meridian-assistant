"""Branch directory + operating hours, from the COMPILED branch record.

The branch directory is extracted from the branch-hours document at compile time
(:mod:`meridian.extraction`) and committed; this module applies deterministic day-of-week
logic to it — no LLM or retrieval at runtime.
"""

from __future__ import annotations

from datetime import date

from ..extraction.schemas import BranchHours
from .loader import load_branches

# weekday() 0..6 (Mon..Sun) → the BranchHours attribute holding that day's hours.
_DAY_ATTRS: tuple[str, ...] = ("mon_fri", "mon_fri", "mon_fri", "mon_fri", "mon_fri", "sat", "sun")


def emergency_line() -> str:
    """Return the 24/7 emergency phone number."""
    return load_branches().emergency_line


def list_branches() -> list[BranchHours]:
    """Return all branch records."""
    return list(load_branches().branches)


def get_branch(name: str) -> BranchHours | None:
    """Return the branch record by name (case-insensitive), or ``None``."""
    for branch in load_branches().branches:
        if branch.name.lower() == name.lower():
            return branch
    return None


def hours_on(branch_name: str, day: date) -> str | None:
    """Return the hours string for a branch on ``day``, or ``None`` if unknown branch."""
    branch = get_branch(branch_name)
    if branch is None:
        return None
    return str(getattr(branch, _DAY_ATTRS[day.weekday()]))


def is_open(branch_name: str, day: date) -> bool:
    """Return True if the branch takes normal bookings on ``day``.

    Sunday ``"emergency"`` and ``"closed"`` both count as not open for normal booking.
    """
    hours = hours_on(branch_name, day)
    return hours is not None and hours not in ("closed", "emergency")
