"""Booking value objects shared across the API, tools, and agent."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AppointmentWindow(BaseModel):
    """A concrete scheduled window: a date plus a start/end time band."""

    date: date
    start_time: str = Field(description='Band start, "HH:MM".')
    end_time: str = Field(description='Band end, "HH:MM".')


class CustomerInfo(BaseModel):
    """Customer contact details (used when ``customer_id`` is unknown)."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
