"""Unit tests for service-area coverage — the booking-critical eligibility core.

Covers every documented edge plus the ZIP-range *gaps* that a naive min-max parser
would wrongly include.
"""

from __future__ import annotations

from meridian.domain.enums import CoverageEligibility, ServiceType
from meridian.knowledge.coverage import check_coverage


def test_fairfax_in_range_all_services() -> None:
    d = check_coverage("22032", ServiceType.HVAC)
    assert d.eligibility is CoverageEligibility.YES
    assert d.source == "documented"
    assert d.primary_branch == "Falls Church"
    assert d.county == "Fairfax"


def test_fairfax_gap_22040_not_covered() -> None:
    # 22040 sits between the [22030-22039] and [22041-22044] segments.
    assert check_coverage("22040", ServiceType.HVAC).eligibility is CoverageEligibility.UNKNOWN


def test_arlington_gap_22210_not_covered() -> None:
    # Arlington is 22201-22209 + 22213; 22210-22212 are gaps.
    assert check_coverage("22210", ServiceType.PLUMBING).eligibility is CoverageEligibility.UNKNOWN


def test_alexandria_electrical_is_pending_but_hvac_yes() -> None:
    assert (
        check_coverage("22305", ServiceType.ELECTRICAL).eligibility is CoverageEligibility.PENDING
    )
    assert check_coverage("22305", ServiceType.HVAC).eligibility is CoverageEligibility.YES


def test_loudoun_plumbing_subcontracted_no_same_day() -> None:
    d = check_coverage("20147", ServiceType.PLUMBING)
    assert d.eligibility is CoverageEligibility.YES
    assert d.flags.sub_contracted is True
    assert d.flags.same_day_blocked is True


def test_loudoun_electrical_unavailable() -> None:
    d = check_coverage("20147", ServiceType.ELECTRICAL)
    assert d.eligibility is CoverageEligibility.NO
    assert d.flags.refer_partner is None


def test_prince_georges_electrical_refers_ecopower() -> None:
    d = check_coverage("20708", ServiceType.ELECTRICAL)
    assert d.eligibility is CoverageEligibility.NO
    assert d.flags.refer_partner == "EcoPower"


def test_umd_20742_coordination_flag() -> None:
    d = check_coverage("20742", ServiceType.HVAC)
    assert d.eligibility is CoverageEligibility.YES
    assert d.flags.coordination_required is True


def test_montgomery_electrical_yes() -> None:
    assert check_coverage("20814", ServiceType.ELECTRICAL).eligibility is CoverageEligibility.YES


def test_22046_override_low_confidence() -> None:
    # Test #3 / ASSUMPTIONS #1: serviceable via branch-city override, but disclosed.
    d = check_coverage("22046", ServiceType.HVAC)
    assert d.eligibility is CoverageEligibility.YES
    assert d.source == "override"
    assert d.confidence == "low"


def test_manassas_20110_out_of_area() -> None:
    # Test #9: not listed anywhere -> unknown -> escalate.
    assert (
        check_coverage("20110", ServiceType.ELECTRICAL).eligibility is CoverageEligibility.UNKNOWN
    )


def test_south_zip_unknown_not_no() -> None:
    # South has branches but no coverage doc: must be UNKNOWN, distinct from NO.
    assert check_coverage("21401", ServiceType.HVAC).eligibility is CoverageEligibility.UNKNOWN


def test_invalid_zip_is_unknown() -> None:
    assert check_coverage("2204", ServiceType.HVAC).eligibility is CoverageEligibility.UNKNOWN
    assert check_coverage("abcde", ServiceType.HVAC).eligibility is CoverageEligibility.UNKNOWN
