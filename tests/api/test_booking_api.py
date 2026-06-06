"""Contract + behaviour tests for the mock Booking API and BookingService."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from app.main import create_app
from app.schemas import CreateBookingRequest, ModifyRequest
from app.seed import build_seed_store
from app.service import LATE_CANCEL_FEE, NO_SHOW_FEE, BookingService, cancellation_fee
from fastapi.testclient import TestClient

from meridian.clock import CANONICAL_NOW, EASTERN, FrozenClock
from meridian.domain.enums import (
    Channel,
    CreateStatus,
    JobType,
    ModifyAction,
    ModifyStatus,
    ServiceType,
    Window,
)

AGENT = {"Authorization": "Bearer mock-agent-token"}


def _svc_at(now: datetime) -> BookingService:
    return BookingService(clock=FrozenClock(now), store=build_seed_store())


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_svc_at(CANONICAL_NOW)))


# --------------------------------------------------------------------- fees (pure)
def test_cancellation_fee_boundaries() -> None:
    assert cancellation_fee(25) == 0
    assert cancellation_fee(24.0) == LATE_CANCEL_FEE  # exactly 24h -> $35
    assert cancellation_fee(2.0) == LATE_CANCEL_FEE  # exactly 2h -> $35
    assert cancellation_fee(1.99) == NO_SHOW_FEE
    assert cancellation_fee(-3) == NO_SHOW_FEE  # no-show


def test_cancel_more_than_24h_is_free() -> None:
    svc = _svc_at(CANONICAL_NOW)  # Jan-20 09:00; BK-00391042 is Jan-21 11:00 (~26h)
    resp = svc.modify_booking("BK-00391042", ModifyRequest(action=ModifyAction.CANCEL))
    assert resp.status is ModifyStatus.CANCELLED
    assert resp.fee_applied == 0.0
    assert resp.waiver_used is False


def test_cancel_under_2h_uses_waiver_when_available() -> None:
    svc = _svc_at(datetime(2026, 1, 20, 13, 0, tzinfo=EASTERN))  # 1h before the 14:00 slot
    resp = svc.modify_booking("BK-00477700", ModifyRequest(action=ModifyAction.CANCEL))
    assert resp.fee_applied == 0.0
    assert resp.waiver_used is True


def test_cancel_under_2h_charges_75_when_waiver_used() -> None:
    svc = _svc_at(datetime(2026, 1, 20, 13, 0, tzinfo=EASTERN))
    resp = svc.modify_booking("BK-00477777", ModifyRequest(action=ModifyAction.CANCEL))
    assert resp.fee_applied == float(NO_SHOW_FEE)
    assert resp.waiver_used is False


def test_reschedule_more_than_24h_is_free_with_new_window() -> None:
    svc = _svc_at(CANONICAL_NOW)
    resp = svc.modify_booking(
        "BK-00400022",
        ModifyRequest(
            action=ModifyAction.RESCHEDULE, new_date=date(2026, 1, 24), new_window=Window.AFTERNOON
        ),
    )
    assert resp.status is ModifyStatus.RESCHEDULED
    assert resp.fee_applied == 0.0
    assert resp.new_appointment_window is not None
    assert (resp.new_appointment_window.start_time, resp.new_appointment_window.end_time) == (
        "14:00",
        "18:00",
    )


def test_same_day_reschedule_to_next_week_is_a_late_cancel() -> None:
    svc = _svc_at(datetime(2026, 1, 20, 13, 0, tzinfo=EASTERN))  # 1h before slot
    resp = svc.modify_booking(
        "BK-00477777",  # CID-1005 waiver already used -> charged
        ModifyRequest(
            action=ModifyAction.RESCHEDULE, new_date=date(2026, 1, 27), new_window=Window.MORNING
        ),
    )
    assert resp.fee_applied == float(NO_SHOW_FEE)


def test_same_day_move_is_free() -> None:
    svc = _svc_at(datetime(2026, 1, 20, 13, 0, tzinfo=EASTERN))
    resp = svc.modify_booking(
        "BK-00477777",
        ModifyRequest(
            action=ModifyAction.RESCHEDULE, new_date=date(2026, 1, 20), new_window=Window.AFTERNOON
        ),
    )
    assert resp.fee_applied == 0.0


# --------------------------------------------------------------- create + idempotency
def test_create_is_idempotent_and_records_one_mutation() -> None:
    svc = _svc_at(CANONICAL_NOW)
    req = CreateBookingRequest(
        customer_id="CID-2000",
        service_type=ServiceType.HVAC,
        job_type=JobType.TUNE_UP,
        zip_code="22030",
        preferred_date=date(2026, 1, 28),
        preferred_window=Window.MORNING,
        channel=Channel.AGENT,
    )
    first = svc.create_booking(req)
    second = svc.create_booking(req)
    assert first.status is CreateStatus.CONFIRMED
    assert first.booking_id == second.booking_id  # deduped
    assert [m.op for m in svc.store.mutations] == ["create"]


# ----------------------------------------------------------------------- HTTP layer
def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "customer_id": "CID-3000",
        "service_type": "hvac",
        "job_type": "tune_up",
        "zip_code": "22032",
        "preferred_date": "2026-01-28",
        "preferred_window": "morning",
        "channel": "agent",
    }
    body.update(overrides)
    return body


def test_http_requires_token(client: TestClient) -> None:
    assert client.get("/v1/bookings/BK-00391042").status_code == 401


def test_http_channel_mismatch_is_forbidden(client: TestClient) -> None:
    resp = client.post("/v1/bookings", json=_create_body(channel="web_chat"), headers=AGENT)
    assert resp.status_code == 403


def test_http_create_confirmed(client: TestClient) -> None:
    resp = client.post("/v1/bookings", json=_create_body(), headers=AGENT)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["assigned_branch"] == "Falls Church"
    assert data["confirmation_sent"] is True
    assert data["booking_id"].startswith("BK-")


def test_http_create_out_of_area(client: TestClient) -> None:
    body = _create_body(service_type="electrical", job_type="diagnostic", zip_code="20147")
    assert client.post("/v1/bookings", json=body, headers=AGENT).json()["status"] == "out_of_area"


def test_http_create_pending(client: TestClient) -> None:
    body = _create_body(service_type="electrical", job_type="diagnostic", zip_code="22305")
    resp = client.post("/v1/bookings", json=body, headers=AGENT).json()
    assert resp["status"] == "pending_availability"


def test_http_create_beyond_60_days_rejected(client: TestClient) -> None:
    resp = client.post(
        "/v1/bookings", json=_create_body(preferred_date="2026-05-01"), headers=AGENT
    )
    assert resp.status_code == 400


def test_http_get_with_owner_returns_pii(client: TestClient) -> None:
    data = client.get("/v1/bookings/BK-00391042?customer_id=CID-1001", headers=AGENT).json()
    assert data["status"] == "confirmed"
    assert data["tech_name"] == "Dana Reyes"
    assert data["notes"] is not None


def test_http_get_en_route_returns_eta(client: TestClient) -> None:
    data = client.get("/v1/bookings/BK-00512883", headers=AGENT).json()
    assert data["status"] == "en_route"
    assert data["tech_eta_minutes"] == 12


def test_http_get_confirmed_sibling_has_no_eta(client: TestClient) -> None:
    data = client.get("/v1/bookings/BK-00512884", headers=AGENT).json()
    assert data["status"] == "confirmed"
    assert data["tech_eta_minutes"] is None


def test_http_get_not_found(client: TestClient) -> None:
    assert client.get("/v1/bookings/BK-99999999", headers=AGENT).status_code == 404


def test_http_pii_ownership_mismatch_forbidden(client: TestClient) -> None:
    resp = client.get("/v1/bookings/BK-00399999?customer_id=CID-9999", headers=AGENT)
    assert resp.status_code == 403


def test_http_pii_withheld_without_owner(client: TestClient) -> None:
    data = client.get("/v1/bookings/BK-00399999", headers=AGENT).json()
    assert data["status"] == "confirmed"
    assert data["notes"] is None  # PII withheld without ownership


def test_http_completed_invoice_is_pii_gated(client: TestClient) -> None:
    owned = client.get("/v1/bookings/BK-00388000?customer_id=CID-1006", headers=AGENT).json()
    assert owned["invoice_total"] == 275.0
    masked = client.get("/v1/bookings/BK-00388000", headers=AGENT).json()
    assert masked["invoice_total"] is None
