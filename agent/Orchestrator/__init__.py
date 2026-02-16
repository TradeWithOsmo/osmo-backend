"""
Orchestrator package public surface.

Keep imports lazy to avoid pulling optional heavy deps (LLM providers) when
callers only need lightweight modules (e.g. tool registry inspection/tests).
"""

from __future__ import annotations

from typing import Any

__all__ = ["AgenticTradingRuntime", "runtime_trace_store", "ToolOrchestrator", "ReasoningOrchestrator"]


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name == "AgenticTradingRuntime":
        from .runtime import AgenticTradingRuntime

        return AgenticTradingRuntime
    if name == "runtime_trace_store":
        from .trace_store import runtime_trace_store

        return runtime_trace_store
    if name == "ToolOrchestrator":
        from .tool_orchestrator import ToolOrchestrator

        return ToolOrchestrator
    if name == "ReasoningOrchestrator":
        from .reasoning_orchestrator import ReasoningOrchestrator

        return ReasoningOrchestrator
    raise AttributeError(name)
