"""Minimal web demo for the Meridian assistant — a thin FastAPI shell over the SAME agent.

This process serves a static chat page (``web/``) and proxies two routes to the identical
:class:`AgentRunner` the CLI uses, so the browser exercises the *same* confirm-before-commit path
— a booking commits only after an explicit **Approve**. It wires the in-process Booking double, so
the whole demo runs in one process with no separate API server.

Like ``cli.py`` this module is a **composition root** (importing ``app/`` here is intentional;
the library never depends on the app). The runner is built lazily on first request, so importing
this module — e.g. for tests that inject a fake runner — does not load the retrieval index. The
repository and the evaluation harness run fully without this demo.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.seed import build_seed_store
from app.service import BookingService
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from meridian.agent import AgentRunner, TurnResult
from meridian.clock import CANONICAL_NOW, FrozenClock
from meridian.domain.enums import Channel
from meridian.llm.client import LLMClient, LLMUnavailableError
from meridian.retrieval.retriever import HybridRetriever

_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
_NEEDS_KEY = (
    "This message isn't in the offline cache, so the live agent needs ANTHROPIC_API_KEY. "
    "Try one of the suggested prompts (cached, keyless), or set the key in .env."
)


class MessageIn(BaseModel):
    """A new customer message for a session."""

    message: str


class ConfirmIn(BaseModel):
    """An approve/decline decision for a pending booking confirmation."""

    decision: str


def build_web_runner() -> AgentRunner:
    """Wire the agent runner for the demo (frozen clock, web_chat channel, in-process double)."""
    clock = FrozenClock(CANONICAL_NOW)
    return AgentRunner(
        llm=LLMClient(),
        retriever=HybridRetriever.load(),
        booking_client=BookingService(clock=clock, store=build_seed_store()),
        clock=clock,
        channel=Channel.WEB_CHAT,
    )


def _payload(result: TurnResult) -> dict[str, Any]:
    """Serialise a turn result for the browser (message, citations, proposed action, trace)."""
    return {
        "kind": result.kind,
        "message": result.message,
        "preview": result.preview,
        "proposed_action": result.proposed_action,
        "citations": result.trace.citations if result.trace else [],
        "trace": result.trace.model_dump(mode="json") if result.trace else None,
    }


def create_app(runner: AgentRunner | None = None) -> FastAPI:
    """Create the demo app; ``runner`` may be injected (tests) or built lazily on first request."""
    app = FastAPI(title="Meridian Assistant — Web Demo", version="1.0.0")
    holder: dict[str, AgentRunner | None] = {"runner": runner}
    lock = threading.Lock()  # one shared runner/store/checkpointer → serialise turns

    def _runner() -> AgentRunner:
        current = holder["runner"]
        if current is None:
            current = build_web_runner()
            holder["runner"] = current
        return current

    @app.post("/api/sessions/{session_id}/messages")
    def post_message(session_id: str, body: MessageIn) -> JSONResponse:
        """Run a new customer message; returns an answer, a handoff, or a confirmation prompt."""
        try:
            with lock:
                result = _runner().run_turn(session_id, body.message)
        except LLMUnavailableError:
            return JSONResponse(status_code=503, content={"kind": "error", "message": _NEEDS_KEY})
        return JSONResponse(content=_payload(result))

    @app.post("/api/sessions/{session_id}/confirm")
    def post_confirm(session_id: str, body: ConfirmIn) -> JSONResponse:
        """Resume a paused booking with the customer's approve/decline decision."""
        try:
            with lock:
                result = _runner().confirm_turn(session_id, body.decision)
        except LLMUnavailableError:
            return JSONResponse(status_code=503, content={"kind": "error", "message": _NEEDS_KEY})
        return JSONResponse(content=_payload(result))

    if _WEB_DIR.is_dir():
        # Registered last so the /api routes take precedence; html=True serves index.html at "/".
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    return app


app = create_app()
