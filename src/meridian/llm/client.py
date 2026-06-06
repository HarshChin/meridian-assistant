"""Anthropic LLM client: structured output via forced tool-use + on-disk response cache.

A structured call forces the model to call one tool whose input schema is the target
pydantic model's JSON schema, then validates the tool input into that model. Responses are
cached on disk keyed by the full request (model + prompts + schema), so extraction is
deterministic (temperature 0) and reproducible — and runs keyless once the cache is built
(committed). The cache stores only model outputs, never the API key.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from anthropic.types import TextBlock, ToolUseBlock
from pydantic import BaseModel, Field

from ..config import get_settings

T = TypeVar("T", bound=BaseModel)

_MAX_TOKENS = 8192


class LLMUnavailableError(RuntimeError):
    """Raised when a live call is needed but no API key is configured."""


class LLMTruncationError(RuntimeError):
    """Raised when a structured response is cut off at ``max_tokens`` (likely incomplete)."""


class AgentToolCall(BaseModel):
    """A tool the model chose to call (id-free: the agent loop assigns deterministic ids)."""

    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(BaseModel):
    """One assistant turn from a tool-use ``converse`` call: free text and/or tool calls."""

    text: str = ""
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    stop_reason: str = ""


class LLMClient:
    """Caching Anthropic client for structured (schema-validated) extraction."""

    def __init__(self, model: str | None = None, cache_dir: Path | None = None) -> None:
        """Initialise with an optional model + cache dir (defaults from settings)."""
        settings = get_settings()
        self._model = model or settings.agent_model
        self._cache_dir = cache_dir or settings.llm_cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._api_key = settings.anthropic_api_key
        self._client: anthropic.Anthropic | None = None

    def _client_or_raise(self) -> anthropic.Anthropic:
        if not self._api_key:
            raise LLMUnavailableError(
                "No cache hit and ANTHROPIC_API_KEY is unset — cannot make a live call."
            )
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _cache_key(self, system: str, user: str, schema: type[BaseModel]) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "system": system,
                "user": user,
                "schema": schema.__name__,
                "json_schema": schema.model_json_schema(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Return a schema-validated extraction for the prompt (cached, temperature 0)."""
        cache_path = self._cache_dir / f"{self._cache_key(system, user, schema)}.json"
        if cache_path.exists():
            return schema.model_validate_json(cache_path.read_text(encoding="utf-8"))

        tool: dict[str, Any] = {
            "name": "emit",
            "description": f"Return the extracted {schema.__name__}.",
            "input_schema": schema.model_json_schema(),
        }
        # Plain dict literals for messages/tools/tool_choice are valid per the Anthropic SDK
        # docs but don't satisfy its strict overloaded TypedDicts under mypy.
        response = self._client_or_raise().messages.create(  # type: ignore[call-overload]
            model=self._model,
            max_tokens=_MAX_TOKENS,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit"},
        )
        if response.stop_reason == "max_tokens":
            raise LLMTruncationError(
                f"{schema.__name__} extraction hit max_tokens ({_MAX_TOKENS}); the record is "
                "likely incomplete. Raise the limit or shard the extraction per entity."
            )
        block = next(b for b in response.content if isinstance(b, ToolUseBlock))
        result = schema.model_validate(block.input)
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def _conv_cache_key(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> str:
        payload = json.dumps(
            {"model": self._model, "system": system, "messages": messages, "tools": tools},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentTurn:
        """Run one tool-use turn (the model decides text vs tool calls); cached, temperature 0.

        The returned tool calls are id-free — the agent loop assigns deterministic ids when it
        appends the tool_use / tool_result blocks, so the conversation (and this cache key) stays
        reproducible across runs regardless of the API's non-deterministic tool ids.
        """
        cache_path = self._cache_dir / f"conv_{self._conv_cache_key(system, messages, tools)}.json"
        if cache_path.exists():
            return AgentTurn.model_validate_json(cache_path.read_text(encoding="utf-8"))

        response = self._client_or_raise().messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            temperature=0,
            system=system,
            messages=messages,  # type: ignore[arg-type]  # plain dicts accepted at runtime
            tools=tools,  # type: ignore[arg-type]
        )
        if response.stop_reason == "max_tokens":
            raise LLMTruncationError(
                f"agent turn hit max_tokens ({_MAX_TOKENS}); the response is likely incomplete."
            )
        text = "".join(b.text for b in response.content if isinstance(b, TextBlock))
        tool_calls = [
            AgentToolCall(name=b.name, input=dict(b.input) if isinstance(b.input, dict) else {})
            for b in response.content
            if isinstance(b, ToolUseBlock)
        ]
        turn = AgentTurn(text=text, tool_calls=tool_calls, stop_reason=response.stop_reason or "")
        cache_path.write_text(turn.model_dump_json(indent=2), encoding="utf-8")
        return turn
