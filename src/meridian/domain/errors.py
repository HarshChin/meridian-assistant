"""Typed domain errors.

Distinct exception types let the agent/API map failures to the right customer
response (validation message vs. ownership refusal vs. a hard safety stop) instead
of leaking stack traces.
"""

from __future__ import annotations


class MeridianError(Exception):
    """Base class for all domain errors."""


class InvalidInputError(MeridianError):
    """Input failed validation (bad enum, malformed ZIP, out-of-range date)."""


class OutOfAreaError(MeridianError):
    """The requested ZIP is not in a serviceable area."""


class OwnershipError(MeridianError):
    """A booking lookup failed the PII/ownership check."""


class BookingNotFoundError(MeridianError):
    """No booking exists for the given id."""


class MutationOutsideCommitError(MeridianError):
    """A state-changing tool was invoked outside the ``commit`` node.

    Raised by the read-only tool executor as a hard guarantee that bookings can
    only be created/modified after an explicit, confirmed ``commit`` step.
    """
