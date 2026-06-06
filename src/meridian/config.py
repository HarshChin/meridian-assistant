"""Application settings, loaded from environment variables / a local ``.env`` file.

Every tunable (model ids, retrieval knobs, paths, the canonical demo clock) lives
here so the rest of the codebase depends on one typed object instead of reading the
environment ad hoc.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""Repository root (``D:/meridian``); two levels up from ``src/meridian``."""


class Settings(BaseSettings):
    """Typed application configuration.

    Values come from ``MERIDIAN_*`` environment variables (or a ``.env`` file). The
    Anthropic key additionally accepts the conventional ``ANTHROPIC_API_KEY`` name.
    """

    model_config = SettingsConfigDict(
        env_prefix="MERIDIAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MERIDIAN_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        description="Anthropic key; the deterministic eval tier runs without it.",
    )
    agent_model: str = Field(default="claude-sonnet-4-6", description="Agent + answer model.")
    classifier_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Cheap intent / emergency-paraphrase classifier.",
    )
    judge_model: str = Field(
        default="claude-sonnet-4-6",
        description="Eval groundedness judge (stronger than generator).",
    )

    # --- Paths ---
    files_dir: Path = Field(default=PROJECT_ROOT / "files", description="Provided source PDFs.")
    data_dir: Path = Field(default=PROJECT_ROOT / "data", description="Generated data + index.")

    # --- Retrieval ---
    embed_model: str = Field(default="BAAI/bge-base-en-v1.5", description="fastembed model id.")
    top_k: int = Field(default=5, description="Chunks handed to the answer model.")
    candidate_k: int = Field(default=8, description="Candidates fetched per retriever leg.")
    rrf_k: int = Field(default=15, description="RRF constant, tuned for a small corpus (not 60).")
    tau_high: float = Field(default=0.55, description="Dense-cosine floor for HIGH confidence.")
    tau_low: float = Field(default=0.35, description="Dense-cosine floor below which we abstain.")

    # --- Booking API ---
    booking_api_base_url: str = Field(
        default="http://127.0.0.1:8000/v1", description="Mock Booking API base URL."
    )

    # --- Determinism ---
    frozen_now: datetime | None = Field(
        default=None, description="If set, inject a FrozenClock at this instant (demos/eval)."
    )

    @property
    def index_dir(self) -> Path:
        """Directory holding the committed retrieval index."""
        return self.data_dir / "index"

    @property
    def corpus_dir(self) -> Path:
        """Directory holding extracted, committed corpus markdown."""
        return self.data_dir / "corpus"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
