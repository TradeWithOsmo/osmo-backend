from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .tool_registry import get_tool_registry
from .tool_modes import WRITE_TOOL_NAMES, NAV_TOOL_NAMES, classify_tool_mode
from ..Schema.agent_runtime import AgentPlan, ToolCall, ToolResult


ToolFunc = Callable[..., Awaitable[Any]]


class ToolOrchestrator:
    """
    Tool execution phase:
    resolve tool id -> execute with timeout -> normalize result.
    """

    def __init__(self, registry: Optional[Dict[str, ToolFunc]] = None, tool_timeout_sec: float = 8.0):
        self.registry: Dict[str, ToolFunc] = dict(registry or get_tool_registry())
        self.tool_timeout_sec = float(tool_timeout_sec)
        self._write_tools: Set[str] = set(WRITE_TOOL_NAMES)
        self._nav_tools: Set[str] = set(NAV_TOOL_NAMES)

    def set_registry(self, registry: Dict[str, ToolFunc]) -> None:
        self.registry = dict(registry or {})

    def _resolve_tool(self, tool_name: str) -> Tuple[Optional[ToolFunc], str]:
        fn = self.registry.get(tool_name)
        if fn is not None:
            return fn, tool_name

        # Allow namespace style ids such as "tradingview.add_indicator".
        if "." in tool_name:
            short_name = tool_name.split(".")[-1]
            fn = self.registry.get(short_name)
            if fn is not None:
                return fn, short_name

        return None, tool_name

    def classify_tool_mode(self, tool_name: str) -> str:
        _, resolved_name = self._resolve_tool(tool_name)
        return classify_tool_mode(resolved_name)

    def _check_mode_gate(self, resolved_name: str, tool_states: Optional[Dict[str, Any]]) -> Optional[ToolResult]:
        mode = self.classify_tool_mode(resolved_name)
        if mode != "write":
            return None
        write_enabled = bool((tool_states or {}).get("write"))
        if write_enabled:
            return None
        message = (
            f"Tool '{resolved_name}' requires write mode. "
            "Enable 'Allow Write' to run chart mutation tools."
        )
        return ToolResult(
            name=resolved_name,
            args={},
            ok=False,
            error=message,
            data={"error": message, "required_mode": "write"},
        )

    async def run_tool(self, call: ToolCall, tool_states: Optional[Dict[str, Any]] = None) -> ToolResult:
        fn, resolved_name = self._resolve_tool(call.name)
        if fn is None:
            return ToolResult(
                name=call.name,
                args=call.args,
                ok=False,
                error=f"Unknown tool: {call.name}",
                data={"error": f"Unknown tool: {call.name}"},
            )

        gate = self._check_mode_gate(resolved_name, tool_states=tool_states)
        if gate is not None:
            gate.args = call.args
            return gate

        start = time.perf_counter()
        try:
            data = await asyncio.wait_for(fn(**call.args), timeout=self.tool_timeout_sec)
            latency = int((time.perf_counter() - start) * 1000)
            has_error = isinstance(data, dict) and bool(data.get("error"))
            return ToolResult(
                name=resolved_name,
                args=call.args,
                ok=not has_error,
                error=data.get("error") if has_error else None,
                data=data,
                latency_ms=latency,
            )
        except asyncio.TimeoutError:
            latency = int((time.perf_counter() - start) * 1000)
            message = f"Tool timeout after {self.tool_timeout_sec:.1f}s: {resolved_name}"
            return ToolResult(
                name=resolved_name,
                args=call.args,
                ok=False,
                error=message,
                data={"error": message, "code": "tool_timeout"},
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                name=resolved_name,
                args=call.args,
                ok=False,
                error=str(exc),
                data={"error": str(exc)},
                latency_ms=latency,
            )

    async def run_plan_tools(
        self,
        plan: AgentPlan,
        max_calls: int = 6,
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> List[ToolResult]:
        if not plan or not plan.tool_calls:
            return []
        results: List[ToolResult] = []
        for call in plan.tool_calls[: max(0, int(max_calls))]:
            results.append(await self.run_tool(call, tool_states=tool_states))
        return results
