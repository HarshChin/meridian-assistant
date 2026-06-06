"""Structured, hand-verified knowledge: service-area coverage and branch hours.

Booking-critical lookups live here (deterministic code over curated YAML), kept
separate from the RAG pipeline which only answers prose knowledge.
"""

from __future__ import annotations

from .branches import emergency_line, get_branch, hours_on, is_open, list_branches
from .coverage import check_coverage

__all__ = [
    "check_coverage",
    "emergency_line",
    "get_branch",
    "hours_on",
    "is_open",
    "list_branches",
]
