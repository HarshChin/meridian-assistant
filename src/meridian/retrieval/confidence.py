"""Retrieval-confidence / abstention signal (no LLM).

A LOW signal on a grounded-only question routes the agent to a human handoff instead of
answering from weak context. Thresholds live in config and are tuned on a held-out slice.
"""

from __future__ import annotations

from enum import StrEnum

from ..config import get_settings


class Confidence(StrEnum):
    """How confident retrieval is that the corpus can answer the query."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def assess(top_cosine: float) -> Confidence:
    """Map the best dense cosine of the retrieved set to a confidence band."""
    settings = get_settings()
    if top_cosine >= settings.tau_high:
        return Confidence.HIGH
    if top_cosine < settings.tau_low:
        return Confidence.LOW
    return Confidence.MEDIUM
