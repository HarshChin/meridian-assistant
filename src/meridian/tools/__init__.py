"""LLM tool surface: capability-tagged tools + a registry enforcing confirm-before-mutate."""

from .base import Capability, Tool, ToolRegistry, ToolResult
from .registry import build_registry

__all__ = ["Capability", "Tool", "ToolRegistry", "ToolResult", "build_registry"]
