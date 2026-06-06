"""Business policy VALUES, loaded from ``data/policy.yaml`` (provenance-tagged).

The deterministic LOGIC that applies these lives in code (fees, the Booking service,
windows); only the numbers/dates live in YAML, so there is one source of truth, no drift
from the knowledge pack, and a clean hook for per-branch policy overrides in production.
"""

from __future__ import annotations

import functools
from datetime import date

import yaml
from pydantic import BaseModel

from .config import get_settings


class CancellationPolicy(BaseModel):
    """Cancellation / no-show fee schedule (doc 07)."""

    free_notice_hours: int
    late_cancel_threshold_hours: int
    late_cancel_fee_usd: int
    no_show_fee_usd: int
    no_show_waiver_period_months: int


class SurchargePolicy(BaseModel):
    """After-hours / Sunday-holiday surcharge schedule (doc 03)."""

    weekday_after_hours_usd: int
    sunday_holiday_usd: int
    business_hours_start_hour: int
    business_hours_end_hour: int


class BookingPolicy(BaseModel):
    """Booking constraints + appointment-window bands (doc 12)."""

    max_advance_days: int
    notes_max_length: int
    windows: dict[str, tuple[str, str]]


class Policy(BaseModel):
    """Top-level business policy loaded from ``data/policy.yaml``."""

    version: str
    cancellation: CancellationPolicy
    surcharges: SurchargePolicy
    diagnostic_fees_usd: dict[str, int]
    emergency_dispatch_fees_usd: dict[str, int]
    booking: BookingPolicy
    federal_holidays: list[date]


@functools.lru_cache(maxsize=1)
def get_policy() -> Policy:
    """Load and cache the business policy from ``data/policy.yaml``."""
    path = get_settings().data_dir / "policy.yaml"
    return Policy(**yaml.safe_load(path.read_text(encoding="utf-8")))
