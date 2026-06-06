"""Value objects describing a service-area eligibility decision."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import CoverageEligibility, Region, ServiceType


class CoverageFlags(BaseModel):
    """Side-conditions attached to a coverage decision."""

    same_day_blocked: bool = Field(default=False, description="No same-day service (e.g. Loudoun).")
    sub_contracted: bool = Field(default=False, description="Delivered via a sub-contractor.")
    surcharge_possible: bool = Field(
        default=False, description="A $45 travel surcharge may apply (>20 mi)."
    )
    coordination_required: bool = Field(
        default=False, description="Needs facilities-office coordination (e.g. UMD 20742)."
    )
    refer_partner: str | None = Field(
        default=None, description="Refer the customer to this partner (e.g. EcoPower)."
    )


class CoverageDecision(BaseModel):
    """Result of :func:`meridian.knowledge.coverage.check_coverage`.

    ``source`` and ``confidence`` make inference explicit: a decision derived from
    an inferred branch-city override (e.g. ZIP 22046) is ``source="override"`` /
    ``confidence="low"`` and must be disclosed as such — never presented as a
    documented fact.
    """

    zip_code: str
    service_type: ServiceType
    eligibility: CoverageEligibility
    region: Region | None = None
    county: str | None = None
    primary_branch: str | None = None
    overflow_branch: str | None = None
    flags: CoverageFlags = Field(default_factory=CoverageFlags)
    source: str = Field(description='"documented" | "override" | "none".')
    confidence: str = Field(default="high", description='"high" | "low".')
    citation: str = Field(description="Human-readable source reference for the trace/answer.")
    rationale: str = Field(description="Short, customer-safe explanation of the outcome.")
