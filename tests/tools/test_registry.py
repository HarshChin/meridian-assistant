"""The capability split — the confirm-before-mutate safety core (no external deps)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from meridian.domain.errors import InvalidInputError, MutationOutsideCommitError
from meridian.tools.base import Capability, Tool, ToolRegistry, ToolResult


class _Empty(BaseModel):
    pass


class _NeedsField(BaseModel):
    x: int


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            "reader",
            "",
            Capability.READ_ONLY,
            _Empty,
            lambda a: ToolResult(tool="reader", summary="ok"),
        )
    )
    reg.register(
        Tool(
            "writer",
            "",
            Capability.MUTATING,
            _Empty,
            lambda a: ToolResult(tool="writer", summary="done"),
        )
    )
    reg.register(
        Tool(
            "strict",
            "",
            Capability.READ_ONLY,
            _NeedsField,
            lambda a: ToolResult(tool="strict", summary="ok"),
        )
    )
    return reg


def test_mutating_tool_blocked_outside_commit() -> None:
    with pytest.raises(MutationOutsideCommitError):
        _registry().execute("writer", {}, allow_mutations=False)


def test_mutating_tool_runs_in_commit() -> None:
    assert _registry().execute("writer", {}, allow_mutations=True).summary == "done"


def test_read_only_tool_runs_anywhere() -> None:
    assert _registry().execute("reader", {}, allow_mutations=False).ok is True


def test_unknown_tool_raises() -> None:
    with pytest.raises(KeyError):
        _registry().execute("nope", {})


def test_bad_args_raise_invalid_input() -> None:
    with pytest.raises(InvalidInputError):
        _registry().execute("strict", {}, allow_mutations=False)  # missing required 'x'


def test_specs_filter_by_capability() -> None:
    reg = _registry()
    assert {s["name"] for s in reg.specs(mutating=True)} == {"writer"}
    assert {s["name"] for s in reg.specs(mutating=False)} == {"reader", "strict"}
    assert reg.is_mutating("writer") and not reg.is_mutating("reader")
    # specs carry a JSON-schema input for the LLM
    assert reg.get("strict").spec()["input_schema"]["type"] == "object"
