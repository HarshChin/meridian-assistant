"""Synthetic mock fixtures for the Booking API (NOT knowledge-pack facts).

These are made-up personas for the simulated backend, kept in ``data/fixtures/`` so they
are not mistaken for documented facts and stay DRY across the service and seed data.
"""

from __future__ import annotations

import functools

import yaml

from meridian.config import get_settings


@functools.lru_cache(maxsize=1)
def load_technician_roster() -> tuple[str, ...]:
    """Load the deterministic mock technician roster from ``data/fixtures``."""
    path = get_settings().data_dir / "fixtures" / "technicians.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(data["roster"])
