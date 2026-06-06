"""Capability schemas — the SHAPE of facts each booking-critical capability needs.

These pydantic models are the *only* hand-defined artifacts in the knowledge path. A schema
describes what a capability requires (a fee has tiers; coverage has ZIP ranges) — determined
by what the assistant DOES, not by the corpus. Every VALUE is extracted from documents at
compile time, so a corpus of 13 or 13,000 documents uses this same finite set of schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Service-area coverage (docs 01/02)
# --------------------------------------------------------------------------------------


class ZipSegment(BaseModel):
    """An inclusive ZIP-code range; a single ZIP is encoded as ``low == high``."""

    low: int = Field(description="First 5-digit ZIP in the inclusive range.")
    high: int = Field(description="Last 5-digit ZIP in the range (equal to low if a single ZIP).")


class CountyCoverage(BaseModel):
    """Coverage for one county exactly as stated in the document."""

    county: str = Field(description="County (or city) name as written.")
    region: str | None = Field(
        default=None, description="north | central | south, from the document title if stated."
    )
    zip_segments: list[ZipSegment] = Field(description="Covered ZIP ranges; gaps preserved.")
    hvac: str = Field(description="available | pending | not_available | subcontracted")
    plumbing: str = Field(description="available | pending | not_available | subcontracted")
    electrical: str = Field(description="available | pending | not_available | subcontracted")
    primary_branch: str | None = Field(
        default=None, description="Primary branch if a branch table maps this county; else null."
    )
    overflow_branch: str | None = Field(
        default=None, description="Overflow branch; '—' means null."
    )
    same_day_blocked: bool = Field(
        default=False, description="True if the text says no same-day service for this county."
    )
    refer_partner: str | None = Field(
        default=None, description="Partner to refer to for an unavailable service (e.g. EcoPower)."
    )
    coordination_zips: list[int] = Field(
        default_factory=list, description="ZIPs the text says need facilities-office coordination."
    )


class ServiceAreaExtraction(BaseModel):
    """All county-coverage rows found in the retrieved service-area text."""

    counties: list[CountyCoverage] = Field(description="One entry per county row in the text.")
    out_of_area_policy: str | None = Field(
        default=None, description="What to do for unlisted ZIPs, if the text states it."
    )
    travel_surcharge_usd: int | None = Field(
        default=None, description="Travel-surcharge dollar amount if stated."
    )


# --------------------------------------------------------------------------------------
# Fee schedule (docs 03/04/05/07)
# --------------------------------------------------------------------------------------


class FeeSchedule(BaseModel):
    """Fee values compiled from the cancellation + pricing documents.

    The deterministic LOGIC that applies these (boundary conventions, the once-per-period
    waiver, the warranty/same-day waivers) lives in code; only the values are extracted.
    """

    free_notice_hours: int = Field(
        description="Cancellations with MORE notice than this many hours incur no fee."
    )
    late_cancel_threshold_hours: int = Field(
        description="At/above this many hours notice (and within free_notice) is a late-cancel "
        "fee; below it (or a no-show) is the no-show fee."
    )
    late_cancel_fee_usd: int = Field(description="Late-cancellation fee in USD.")
    no_show_fee_usd: int = Field(description="No-show fee in USD.")
    no_show_waiver_period_months: int = Field(
        description="The no-show fee is waived once per this many months per customer."
    )
    weekday_after_hours_usd: int = Field(
        description="Surcharge for Mon-Sat calls before business-hours start or at/after end."
    )
    sunday_holiday_usd: int = Field(description="Surcharge for Sundays and federal holidays.")
    business_hours_start_hour: int = Field(
        description="Hour (0-23) business hours begin; before this is after-hours."
    )
    business_hours_end_hour: int = Field(
        description="Hour (0-23) business hours end; at/after this is after-hours."
    )
    diagnostic_fees_usd: dict[str, int] = Field(
        description="Flat diagnostic / service-call fee per service line "
        "(keys: hvac, plumbing, electrical)."
    )
    emergency_dispatch_fees_usd: dict[str, int] = Field(
        description="Emergency dispatch fee per service line that documents one (e.g. plumbing)."
    )


# --------------------------------------------------------------------------------------
# Branch directory + hours (doc 08)
# --------------------------------------------------------------------------------------


class BranchHours(BaseModel):
    """Operating hours for one branch, normalised to 24-hour ranges."""

    name: str = Field(description="Branch name as written.")
    region: str = Field(description="north | central | south")
    mon_fri: str = Field(description='Mon-Fri hours as "HH:MM-HH:MM", or "closed", or "emergency".')
    sat: str = Field(description='Saturday hours as "HH:MM-HH:MM", or "closed", or "emergency".')
    sun: str = Field(description='Sunday hours as "HH:MM-HH:MM", or "closed", or "emergency".')


class BranchDirectory(BaseModel):
    """The full branch directory + the 24/7 emergency line."""

    emergency_line: str = Field(description="24/7 emergency phone number as written.")
    branches: list[BranchHours] = Field(description="One entry per branch location.")
