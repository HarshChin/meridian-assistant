"""FastAPI app exposing the mock Booking API over HTTP (doc 12).

The app is a thin HTTP wrapper around :class:`BookingService`. Domain errors are mapped
to status codes; the same service is also used in-process (no HTTP) by the tools/eval.
The mock runs on a :class:`FrozenClock` so the seeded January-2026 bookings stay coherent.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from meridian.clock import CANONICAL_NOW, Clock, FrozenClock
from meridian.config import get_settings
from meridian.domain.enums import Channel
from meridian.domain.errors import BookingNotFoundError, InvalidInputError, OwnershipError

from .auth import require_channel
from .schemas import (
    CreateBookingRequest,
    CreateBookingResponse,
    LookupResponse,
    ModifyRequest,
    ModifyResponse,
)
from .seed import build_seed_store
from .service import BookingService


def _default_service() -> BookingService:
    """Build the default service: a frozen clock + a freshly-seeded store."""
    settings = get_settings()
    clock: Clock = (
        FrozenClock(settings.frozen_now) if settings.frozen_now else FrozenClock(CANONICAL_NOW)
    )
    return BookingService(clock=clock, store=build_seed_store())


def create_app(service: BookingService | None = None) -> FastAPI:
    """Create the FastAPI app, optionally injecting a service (for tests)."""
    svc = service or _default_service()
    app = FastAPI(title="Meridian Mock Booking API", version="1.0.0")

    @app.exception_handler(InvalidInputError)
    async def _bad_input(_request: Request, exc: InvalidInputError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.exception_handler(BookingNotFoundError)
    async def _not_found(_request: Request, exc: BookingNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": f"Booking not found: {exc}"}
        )

    @app.exception_handler(OwnershipError)
    async def _forbidden(_request: Request, exc: OwnershipError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})

    router = APIRouter(prefix="/v1")

    @router.post("/bookings", response_model=CreateBookingResponse)
    def create_booking(
        req: CreateBookingRequest, channel: Channel = Depends(require_channel)
    ) -> CreateBookingResponse:
        if req.channel != channel:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "channel does not match the token's channel scope."
            )
        return svc.create_booking(req)

    @router.get("/bookings/{booking_id}", response_model=LookupResponse)
    def get_booking(
        booking_id: str,
        customer_id: str | None = None,
        _channel: Channel = Depends(require_channel),
    ) -> LookupResponse:
        return svc.get_booking(booking_id, customer_id)

    @router.patch("/bookings/{booking_id}", response_model=ModifyResponse)
    def modify_booking(
        booking_id: str, req: ModifyRequest, _channel: Channel = Depends(require_channel)
    ) -> ModifyResponse:
        return svc.modify_booking(booking_id, req)

    app.include_router(router)
    return app


app = create_app()
