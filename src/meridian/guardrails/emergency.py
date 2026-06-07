"""Emergency detection — a rules-first, recall-biased safety guardrail + an LLM paraphrase union.

Because missing a real emergency is the worst possible failure, detection is rules-FIRST: a
committed, recall-biased keyword set sourced from ``11_faq_emergencies.pdf`` ("What Counts as an
Emergency?"), deliberately code (predictable, never silently changed by an extraction run). The
agent's safety node then layers an LLM paraphrase-catch on top as a **union** — it may only *add*
an emergency the keywords missed, never veto one — so novel wordings ("my furnace died and the
baby is freezing") are still caught. A detected emergency routes straight to the 24/7 line and
never to a booking. The threshold-conditional triggers (no heat below 40°F / no cooling above
95°F) are simplified to recall-biased phrase matches here — see ASSUMPTIONS.md.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class EmergencyAssessment(BaseModel):
    """Outcome of the emergency screen (rules or the LLM union)."""

    is_emergency: bool
    category: str | None = None
    matched: str | None = None


class EmergencyCheck(BaseModel):
    """Schema for the LLM paraphrase-catch (structured, cached)."""

    is_emergency: bool = Field(description="True if the message plausibly describes an emergency.")
    category: str | None = Field(default=None, description="Short emergency category if any.")


# Patterns sourced in intent from 11_faq_emergencies.pdf. Recall-biased but phrased to avoid
# obvious non-emergencies ("AC isn't cooling well", "no heating issues").
_TRIGGERS: tuple[tuple[str, str], ...] = (
    (
        "active_leak",
        r"\b(active leak|water leak|leaking pipe|leaking water|burst pipe|pipe burst|"
        r"flood(ed|ing)?|filling with water|water everywhere)\b|"
        r"\bwater\b.{0,20}\b(pouring|gushing|spraying|spreading|pooling|seeping|soaking)\b|"
        r"\bceiling\b.{0,15}\b(leak|leaking|water|dripping)\b",
    ),
    ("sewage", r"\bsewage\b|\bsewer\b.{0,15}\bback(ing)?[\s-]?up\b"),
    (
        "electrical_hazard",
        r"\b(burning smell|sparking|sparks|electrical fire|electrical hazard|live wire|"
        r"partial power loss)\b|\b(getting|got|being) shocked\b|\belectric(al)? shock\b|"
        r"\bsmell\b.{0,20}\bburn(ing|t)?\b|\bburn(ing|t)?\b.{0,20}\bsmell\b|"
        r"\bsmok(e|ing)\b.{0,15}\b(from|coming|panel|outlet|breaker|wire)\b|"
        r"\b(panel|breaker|outlet|socket|wire)\b.{0,25}\b(buzzing|humming|melting|sparking|crackling)\b|"
        r"\b(buzzing|humming|crackling|melting)\b.{0,20}\b(panel|breaker|outlet|socket|wire)\b",
    ),
    (
        "gas_or_co",
        r"\b(gas leak|gas smell)\b|\bgas\b.{0,10}\bleak(ing)?\b|\bleaking\b.{0,6}\bgas\b|"
        r"\bsmell\b.{0,10}\bgas\b|\bcarbon[\s-]?monoxide\b|\brotten\s+eggs?\b|"
        r"\bco\b.{0,12}\b(alarm|detector|going off)\b",
    ),
    (
        "no_heat",
        r"\b(no heat|heat is out|heat went out|heating is out)\b|"
        r"\bfurnace\b.{0,15}\b(out|dead|died|broke|broken|quit|stopped|failed|not working)\b",
    ),
    (
        "no_cooling",
        r"\b(no cooling|no a/?c|a/?c is out|no air conditioning)\b|"
        r"\bac\b.{0,8}\b(died|quit|stopped|broke|broken|out|dead)\b",
    ),
)


def detect_emergency(text: str) -> EmergencyAssessment:
    """Return the rules-first emergency assessment for a customer message (recall-biased)."""
    lowered = text.lower()
    for category, pattern in _TRIGGERS:
        match = re.search(pattern, lowered)
        if match:
            return EmergencyAssessment(is_emergency=True, category=category, matched=match.group(0))
    return EmergencyAssessment(is_emergency=False)
