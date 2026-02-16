from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .tool_registry import get_tool_registry
from .tool_modes import (
    CHART_WRITE_TOOL_NAMES,
    EXECUTION_WRITE_TOOL_NAMES,
    DECISION_TOOL_NAMES,
    NAV_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    classify_tool_mode,
)
from ..Config.tools_config import TRADE_DECISION_COMPARATORS, TRADE_DECISION_FIELD_ALIASES
from ..Schema.agent_runtime import AgentPlan, ToolCall, ToolResult


import inspect

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
        self._decision_tools: Set[str] = set(DECISION_TOOL_NAMES)

    def set_registry(self, registry: Dict[str, ToolFunc]) -> None:
        self.registry = dict(registry or {})

    @staticmethod
    def _parse_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "on", "yes"}:
                return True
            if normalized in {"0", "false", "off", "no"}:
                return False
            return default
        return bool(value)

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

        states = tool_states or {}
        write_enabled = self._parse_bool(states.get("write"), default=False)
        execution_enabled = self._parse_bool(states.get("execution"), default=False)

        # Chart write tools are gated by Allow Write.
        if resolved_name in CHART_WRITE_TOOL_NAMES:
            if write_enabled:
                return None
            message = (
                f"Tool '{resolved_name}' requires write mode. "
                "Enable 'Allow Write' to run TradingView chart mutation tools."
            )
            return ToolResult(
                name=resolved_name,
                args={},
                ok=False,
                error=message,
                data={"error": message, "required_mode": "write"},
            )

        # Portfolio/order execution tools are gated by execution flag.
        if resolved_name in EXECUTION_WRITE_TOOL_NAMES:
            if execution_enabled:
                return None
            message = (
                f"Tool '{resolved_name}' requires execution mode. "
                "Enable 'execution' to run portfolio/order mutation tools."
            )
            return ToolResult(
                name=resolved_name,
                args={},
                ok=False,
                error=message,
                data={"error": message, "required_mode": "execution"},
            )

        # Conservative default: treat unknown write tools as chart write tools.
        if write_enabled:
            return None
        message = (
            f"Tool '{resolved_name}' requires write mode. "
            "Enable 'Allow Write' to run write tools."
        )
        return ToolResult(
            name=resolved_name,
            args={},
            ok=False,
            error=message,
            data={"error": message, "required_mode": "write"},
        )

    @staticmethod
    def _first_present(payload: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _normalize_side(side: Any) -> str:
        raw = str(side or "").strip().lower()
        if raw == "buy":
            return "long"
        if raw == "sell":
            return "short"
        return raw

    def _normalize_tool_args(self, resolved_name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = dict(args or {})
        if resolved_name not in self._decision_tools:
            return normalized

        validation_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("validation", ("gp", "validation")))
        invalidation_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("invalidation", ("gl", "invalidation")))

        validation_level = self._first_present(normalized, validation_keys)
        invalidation_level = self._first_present(normalized, invalidation_keys)

        if validation_level is not None:
            for key in validation_keys:
                normalized.setdefault(key, validation_level)
        if invalidation_level is not None:
            for key in invalidation_keys:
                normalized.setdefault(key, invalidation_level)

        if "side" in normalized:
            normalized["side"] = self._normalize_side(normalized.get("side"))
        return normalized

    def _build_trade_decision_payload(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        validation_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("validation", ("gp", "validation")))
        invalidation_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("invalidation", ("gl", "invalidation")))
        target_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("targets", ("tp", "tp2", "tp3")))
        risk_keys = tuple(TRADE_DECISION_FIELD_ALIASES.get("risk_controls", ("sl", "trailing_sl", "be", "liq")))

        validation_level = self._first_present(args, validation_keys)
        invalidation_level = self._first_present(args, invalidation_keys)
        if validation_level is None and invalidation_level is None:
            return None

        side = self._normalize_side(args.get("side"))
        if side not in TRADE_DECISION_COMPARATORS:
            side = "long"
        comparator_map = TRADE_DECISION_COMPARATORS.get(side, {})

        return {
            "side": side,
            "validation": {
                "label": "validation",
                "alias": "gp",
                "level": validation_level,
                "comparator": comparator_map.get("validation"),
                "rule": (
                    f"Generate validation decision when price {comparator_map.get('validation')} GP/validation level."
                    if validation_level is not None
                    else "Validation level not set."
                ),
            },
            "invalidation": {
                "label": "invalidation",
                "alias": "gl",
                "level": invalidation_level,
                "comparator": comparator_map.get("invalidation"),
                "rule": (
                    f"Generate invalidation decision when price {comparator_map.get('invalidation')} GL/invalidation level."
                    if invalidation_level is not None
                    else "Invalidation level not set."
                ),
            },
            "targets": {key: args.get(key) for key in target_keys if args.get(key) is not None},
            "risk_controls": {key: args.get(key) for key in risk_keys if args.get(key) is not None},
        }

    def _decorate_tool_data(self, resolved_name: str, args: Dict[str, Any], data: Any) -> Any:
        if resolved_name not in self._decision_tools or not isinstance(data, dict):
            return data

        decision_payload = self._build_trade_decision_payload(args)
        if decision_payload is None:
            return data

        enriched = dict(data)
        existing = enriched.get("decision")
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.setdefault("side", decision_payload.get("side"))
            merged.setdefault("validation", decision_payload.get("validation"))
            merged.setdefault("invalidation", decision_payload.get("invalidation"))
            merged.setdefault("targets", decision_payload.get("targets"))
            merged.setdefault("risk_controls", decision_payload.get("risk_controls"))
            enriched["decision"] = merged
        else:
            enriched["decision"] = decision_payload
        return enriched

    
    def _tool_accepts_kwarg(self, fn: ToolFunc, arg_name: str) -> bool:
        if fn is None:
            return False
        try:
            signature = inspect.signature(fn)
        except Exception:
            # If signature inspection fails (e.g. built-in), assume no.
            return False
        if arg_name in signature.parameters:
            return True
        return any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
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

        call_args = self._normalize_tool_args(resolved_name, call.args)
        
        # Inject tool_states if the tool function accepts it
        if tool_states and self._tool_accepts_kwarg(fn, "tool_states"):
            call_args["tool_states"] = tool_states
            
        gate = self._check_mode_gate(resolved_name, tool_states=tool_states)
        if gate is not None:
            gate.args = call_args
            return gate

        start = time.perf_counter()
        try:
            data = await asyncio.wait_for(fn(**call_args), timeout=self.tool_timeout_sec)
            data = self._decorate_tool_data(resolved_name, call_args, data)
            latency = int((time.perf_counter() - start) * 1000)
            has_error = isinstance(data, dict) and bool(data.get("error"))
            return ToolResult(
                name=resolved_name,
                args=call_args,
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
                args=call_args,
                ok=False,
                error=message,
                data={"error": message, "code": "tool_timeout"},
                latency_ms=latency,
            )
        except Exception as exc:
            latency = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                name=resolved_name,
                args=call_args,
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
