"""Typed Booking API client: HTTP wire contract + in-process parity + error mapping."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from app.main import create_app
from app.seed import build_seed_store
from app.service import BookingService
from fastapi.testclient import TestClient

from meridian.api_client import (
    CreateBookingRequest,
    HttpBookingClient,
    ModifyRequest,
)
from meridian.api_client.base import BookingClient
from meridian.clock import CANONICAL_NOW, FrozenClock
from meridian.domain.enums import (
    Channel,
    CreateStatus,
    JobType,
    ModifyAction,
    ModifyStatus,
    ServiceType,
    Window,
)
from meridian.domain.errors import BookingNotFoundError, InvalidInputError, OwnershipError


def _service() -> BookingService:
    return BookingService(clock=FrozenClock(CANONICAL_NOW), store=build_seed_store())


@pytest.fixture
def http() -> Iterator[HttpBookingClient]:
    # TestClient is an httpx.Client purpose-built for synchronous ASGI, so the HTTP client's
    # real serialisation / auth / status-code mapping is exercised without a live server.
    with TestClient(create_app(_service())) as client:
        yield HttpBookingClient(
            base_url="http://testserver/v1", channel=Channel.AGENT, http_client=client
        )


def _create_req() -> CreateBookingRequest:
    return CreateBookingRequest(
        customer_id="CID-3000",
        service_type=ServiceType.HVAC,
        job_type=JobType.TUNE_UP,
        zip_code="22032",
        preferred_date=date(2026, 1, 28),
        preferred_window=Window.MORNING,
        channel=Channel.AGENT,
    )


def test_inprocess_service_is_a_booking_client() -> None:
    assert isinstance(_service(), BookingClient)


def test_http_create_confirmed(http: HttpBookingClient) -> None:
    resp = http.create_booking(_create_req())
    assert resp.status is CreateStatus.CONFIRMED
    assert resp.assigned_branch == "Falls Church"
    assert resp.confirmation_sent is True


def test_http_not_found_maps_to_domain_error(http: HttpBookingClient) -> None:
    with pytest.raises(BookingNotFoundError):
        http.get_booking("BK-99999999")


def test_http_ownership_mismatch_maps_to_domain_error(http: HttpBookingClient) -> None:
    with pytest.raises(OwnershipError):
        http.get_booking("BK-00399999", customer_id="CID-9999")


def test_http_owner_sees_pii(http: HttpBookingClient) -> None:
    resp = http.get_booking("BK-00391042", customer_id="CID-1001")
    assert resp.tech_name == "Dana Reyes"
    assert resp.notes is not None


def test_http_pii_withheld_without_owner(http: HttpBookingClient) -> None:
    resp = http.get_booking("BK-00391042")  # no customer_id -> owner-only PII withheld
    assert resp.tech_name is None
    assert resp.notes is None


def test_http_bad_token_maps_to_domain_error() -> None:
    # A 401 must surface as a typed domain error, never a raw httpx.HTTPStatusError.
    with TestClient(create_app(_service())) as raw:
        client = HttpBookingClient(
            base_url="http://testserver/v1",
            channel=Channel.AGENT,
            http_client=raw,
            token="not-a-real-token",
        )
        with pytest.raises(InvalidInputError):
            client.get_booking("BK-00391042")


def test_http_modify_cancel(http: HttpBookingClient) -> None:
    resp = http.modify_booking("BK-00391042", ModifyRequest(action=ModifyAction.CANCEL))
    assert resp.status is ModifyStatus.CANCELLED
    assert resp.fee_applied == 0.0


def test_inprocess_and_http_agree_on_lookup(http: HttpBookingClient) -> None:
    in_proc = _service().get_booking("BK-00512883")  # en_route seed
    over_http = http.get_booking("BK-00512883")
    assert (in_proc.status, in_proc.tech_eta_minutes) == (
        over_http.status,
        over_http.tech_eta_minutes,
    )
