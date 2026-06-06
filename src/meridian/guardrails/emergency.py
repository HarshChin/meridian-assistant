"""Emergency detection — a rules-first, recall-biased safety guardrail.

Because missing a real emergency is the worst possible failure, detection does NOT depend on
LLM extraction: the trigger patterns are a committed, recall-biased keyword set sourced from
``11_faq_emergencies.pdf`` ("What Counts as an Emergency?"). An optional LLM paraphrase-catch
(wired in the safety node) may only *add* an emergency (a union), never veto one. A detected
emergency routes straight to a human handoff on the 24/7 line and never to a booking.

This trigger list is deliberately code, not compiled data: a safety classifier must be
predictable and recall-biased, and must not silently change because an extraction run drifted.
The threshold-conditional triggers (no heat below 40°F / no cooling above 95°F) are simplified
to recall-biased phrase matches here — see ASSUMPTIONS.md.
"""

from __future__ import annotations

import re

from pydantic import BaseModel


class EmergencyAssessment(BaseModel):
    """Outcome of the rules-first emergency screen."""

    is_emergency: bool
    category: str | None = None
    matched: str | None = None


# Patterns sourced verbatim-in-intent from 11_faq_emergencies.pdf. Recall-biased: phrased to
# catch emergency wording while avoiding obvious non-emergencies ("AC isn't cooling well").
_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "active_leak",
        r"\b(active leak|water leak|leaking pipe|leaking water|burst pipe|pipe burst|"
        r"flooding|flood)\b",
    ),
    ("sewage", r"\b(sewage|sewer backup)\b"),
    (
        "electrical_hazard",
        r"\b(burning smell|sparking|sparks|electrical fire|electrical hazard|getting shocked|"
        r"partial power loss)\b|\bsmell\b.{0,10}\bburning\b|\bsmoke\b.{0,10}\b(from|coming)\b",
    ),
    ("gas_or_co", r"\b(gas leak|gas smell|carbon monoxide)\b|\bsmell\b.{0,10}\bgas\b"),
    (
        "no_heat",
        r"\b(no heat|heat is out)\b|\bfurnace\b.{0,15}\b(out|dead|broke|broken|not working)\b",
    ),
    ("no_cooling", r"\b(no cooling|no a/?c|a/?c is out|no air conditioning)\b"),
)


def detect_emergency(text: str) -> EmergencyAssessment:
    """Return the rules-first emergency assessment for a customer message (recall-biased)."""
    lowered = text.lower()
    for category, pattern in _TRIGGERS:
        match = re.search(pattern, lowered)
        if match:
            return EmergencyAssessment(is_emergency=True, category=category, matched=match.group(0))
    return EmergencyAssessment(is_emergency=False)
