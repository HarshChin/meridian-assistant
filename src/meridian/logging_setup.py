"""Structured logging (structlog → JSON on stderr) with a stable event contract.

JSON logs make the agent's decisions greppable and feed the eval trace. Call
:func:`configure_logging` once at process start; use :func:`get_logger` elsewhere.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import FilteringBoundLogger


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output on stderr.

    Idempotent enough for repeated test setup; safe to call more than once.

    Args:
        level: Minimum log level name (e.g. ``"INFO"``, ``"DEBUG"``).
    """
    numeric_level = logging.getLevelName(level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name (usually ``__name__``).

    Returns:
        A configured, bound structlog logger.
    """
    return structlog.get_logger(name)
