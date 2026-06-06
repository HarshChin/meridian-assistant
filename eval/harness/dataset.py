"""Eval dataset: labeled customer-message cases + a JSONL loader.

Each case pins the expected behavior the harness asserts: intent/route, whether it should hand
off / be an emergency, whether a booking should commit (and only after an approved confirmation),
which documents the answer must cite, and which normalized facts it must contain. Messages are
chosen so the agent's (cached) LLM calls replay keyless.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "datasets" / "cases.jsonl"


class EvalCase(BaseModel):
    """One labeled evaluation case."""

    id: str
    category: str = Field(description="Capability bucket for grouping results in the report.")
    message: str
    channel: str = "agent"
    now: str | None = Field(
        default=None, description="ISO instant for the frozen clock (default canonical)."
    )
    confirm: str | None = Field(
        default=None, description="Decision to send if a confirmation is requested."
    )

    gold_intent: str | None = None
    expect_kind: str | None = Field(
        default=None,
        description="First-turn result kind: answer | handoff | confirmation_required.",
    )
    expect_route: str | None = Field(default=None, description="Final trace route, e.g. clarify.")
    expect_emergency: bool = False
    expect_committed: bool | None = Field(
        default=None, description="Whether a mutation should be committed."
    )

    must_cite: list[str] = Field(
        default_factory=list, description="Doc-id substrings the citations must include."
    )
    answer_contains: list[str] = Field(
        default_factory=list, description="Normalized facts the reply must contain."
    )
    forbid_mutation_before_confirm: bool = Field(
        default=False, description="Assert the ledger is empty until the confirmation is approved."
    )
    retrieval_gold_doc: str | None = Field(
        default=None,
        description="For knowledge cases: the doc retrieval should surface (recall/MRR).",
    )


def load_cases(path: Path = DEFAULT_CASES) -> list[EvalCase]:
    """Load eval cases from a JSONL file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [EvalCase.model_validate_json(line) for line in lines if line.strip()]
