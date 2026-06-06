"""Tool surface: a capability-tagged registry that enforces confirm-before-mutate.

The safety-critical property — a state-changing tool can run ONLY in the agent's ``commit``
step — is a registry invariant, not a prompt instruction. Every tool is tagged
``READ_ONLY`` or ``MUTATING``; the executor used everywhere except ``commit`` runs with
``allow_mutations=False`` and **raises** :class:`MutationOutsideCommitError` if asked to run a
mutating tool. Only the ``commit`` node calls with ``allow_mutations=True``. A successful prompt
injection therefore still cannot create or change a booking outside an approved commit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..domain.errors import InvalidInputError, MutationOutsideCommitError


class Capability(StrEnum):
    """Whether a tool can change state. Drives the confirm-before-mutate guarantee."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class ToolResult(BaseModel):
    """The structured outcome of a tool call — fed back to the LLM and recorded in the trace."""

    tool: str
    ok: bool = Field(
        default=True, description="False if the tool ran but the action did not succeed."
    )
    summary: str = Field(description="Short human/LLM-readable outcome.")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured payload.")
    citations: list[str] = Field(
        default_factory=list, description="Source references, for traceability."
    )


@dataclass(frozen=True)
class Tool:
    """A registered tool: its LLM-facing spec, capability tag, args schema, and handler."""

    name: str
    description: str
    capability: Capability
    args_model: type[BaseModel]
    handler: Callable[[Any], ToolResult]

    def spec(self) -> dict[str, Any]:
        """Return the Anthropic tool spec (name / description / JSON-schema input)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_model.model_json_schema(),
        }


class ToolRegistry:
    """Holds tools and enforces the read-only/mutating capability split on execution."""

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool (raises on a duplicate name)."""
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return a tool by name (raises ``KeyError`` if unknown)."""
        return self._tools[name]

    def names(self) -> list[str]:
        """Return all registered tool names, sorted."""
        return sorted(self._tools)

    def is_mutating(self, name: str) -> bool:
        """Return True if the named tool is a mutating tool."""
        return self._tools[name].capability is Capability.MUTATING

    def specs(self, *, mutating: bool | None = None) -> list[dict[str, Any]]:
        """Return LLM tool specs, optionally filtered to mutating / non-mutating tools."""
        return [
            tool.spec()
            for tool in self._tools.values()
            if mutating is None or (tool.capability is Capability.MUTATING) == mutating
        ]

    def execute(
        self, name: str, raw_args: dict[str, Any], *, allow_mutations: bool = False
    ) -> ToolResult:
        """Validate args and run a tool, enforcing the capability split.

        Args:
            name: The tool to run.
            raw_args: The (unvalidated) arguments, e.g. an LLM tool-call input.
            allow_mutations: Only ``True`` in the ``commit`` step. When ``False``, invoking a
                mutating tool raises :class:`MutationOutsideCommitError`.

        Raises:
            KeyError: Unknown tool name.
            MutationOutsideCommitError: A mutating tool was invoked with ``allow_mutations=False``.
            InvalidInputError: ``raw_args`` failed the tool's schema validation.
        """
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        tool = self._tools[name]
        if tool.capability is Capability.MUTATING and not allow_mutations:
            raise MutationOutsideCommitError(
                f"'{name}' is a mutating tool; it may run only in the commit step."
            )
        try:
            args = tool.args_model.model_validate(raw_args)
        except ValidationError as exc:
            raise InvalidInputError(f"invalid arguments for '{name}': {exc}") from exc
        return tool.handler(args)
