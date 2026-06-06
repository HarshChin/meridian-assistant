"""HTTP implementation of :class:`BookingClient` (httpx), with channel-scoped bearer auth.

Maps the mock API's status codes back to the typed domain errors so callers handle a 404/403/400
the same way whether they used the in-process service or the wire. An ``httpx.Client`` may be
injected (e.g. bound to the ASGI app) so the wire contract is testable without a live server.
"""

from __future__ import annotations

import httpx

from ..domain.enums import Channel
from ..domain.errors import BookingNotFoundError, InvalidInputError, OwnershipError
from .models import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)


def _extract_detail(response: httpx.Response) -> str:
    """Pull a readable error message from a response (normalising FastAPI's 422 list-of-dicts)."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI request-validation errors are a list of dicts
        msgs = [str(item.get("msg", item)) for item in detail if isinstance(item, dict)]
        return "; ".join(msgs) or "Invalid request."
    return str(detail) if detail is not None else (response.text or "")


class HttpBookingClient:
    """Calls the mock Booking API over HTTP; satisfies the :class:`BookingClient` Protocol."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        channel: Channel = Channel.AGENT,
        *,
        http_client: httpx.Client | None = None,
        token: str | None = None,
    ) -> None:
        """Initialise with a base URL and channel scope (token defaults to the demo token)."""
        self._base_url = base_url.rstrip("/")
        self._channel = channel
        self._token = token or f"mock-{channel.value}-token"
        self._client = http_client or httpx.Client(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Map every error status to a typed domain error — never leak a raw httpx exception.

        404 → not-found, 403 → ownership; everything else with a 4xx/5xx code (validation, auth,
        rate-limit, server error) surfaces as :class:`InvalidInputError` so the tools layer always
        catches it and returns a customer-safe result instead of crashing the turn.
        """
        if response.status_code < 400:
            return
        detail = _extract_detail(response)
        if response.status_code == 404:
            raise BookingNotFoundError(detail or "Booking not found.")
        if response.status_code == 403:
            raise OwnershipError(detail or "Forbidden.")
        raise InvalidInputError(detail or f"Request failed (HTTP {response.status_code}).")

    def create_booking(self, req: CreateBookingRequest) -> CreateBookingResponse:
        """POST a booking; the request's channel must match this client's token scope."""
        response = self._client.post(
            f"{self._base_url}/bookings",
            json=req.model_dump(mode="json"),
            headers=self._headers(),
        )
        self._raise_for_status(response)
        return CreateBookingResponse.model_validate(response.json())

    def get_booking(self, booking_id: str, customer_id: str | None = None) -> LookupResponse:
        """GET a booking; pass ``customer_id`` to unlock PII-gated fields."""
        params = {"customer_id": customer_id} if customer_id is not None else {}
        response = self._client.get(
            f"{self._base_url}/bookings/{booking_id}", params=params, headers=self._headers()
        )
        self._raise_for_status(response)
        return LookupResponse.model_validate(response.json())

    def modify_booking(self, booking_id: str, req: ModifyRequest) -> ModifyResponse:
        """PATCH a booking (reschedule / cancel)."""
        response = self._client.patch(
            f"{self._base_url}/bookings/{booking_id}",
            json=req.model_dump(mode="json"),
            headers=self._headers(),
        )
        self._raise_for_status(response)
        return ModifyResponse.model_validate(response.json())
