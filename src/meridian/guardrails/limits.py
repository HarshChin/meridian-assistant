"""Operational limits for the agent loop."""

from __future__ import annotations

MAX_TOOL_ITERATIONS = 6
"""Cap on read-only tool-use rounds in ``plan_act`` before the agent must answer or hand off.

Bounds latency/cost and stops a tool-call loop; reaching it routes to a human handoff rather
than spinning.
"""
