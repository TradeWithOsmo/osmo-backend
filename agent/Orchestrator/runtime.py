from __future__ import annotations

import json
import inspect
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from .tool_registry import get_tool_registry
from .reasoning_orchestrator import ReasoningOrchestrator
from .tool_orchestrator import ToolOrchestrator
from .execution_adapter import ExecutionAdapter
from ..Schema.agent_runtime import AgentPlan, PlanContext, ToolCall, ToolResult

FIAT_CODES: Set[str] = {
    "USD",
    "EUR",
    "GBP",
    "CHF",
    "JPY",
    "CAD",
    "AUD",
    "NZD",
    "MXN",
    "HKD",
}

USER_ADDRESS_REQUIRED_TOOLS: Set[str] = {
    "adjust_position_tpsl",
    "adjust_all_positions_tpsl",
}


class AgenticTradingRuntime:
    """
    Codex-like runtime loop for trading assistant:
    plan -> guardrail -> tool execution -> structured context for synthesis.
    """

    def __init__(self, tool_timeout_sec: float = 8.0, max_output_chars: int = 1800):
        # Keep _registry for backward compatibility with existing tests/overrides.
        self._registry = get_tool_registry()
        self._tool_timeout_sec = tool_timeout_sec
        self._max_output_chars = max_output_chars
        self.reasoning_orchestrator = ReasoningOrchestrator()
        self.tool_orchestrator = ToolOrchestrator(
            registry=self._registry,
            tool_timeout_sec=tool_timeout_sec,
        )

    def _has_explicit_execute_phrase(self, message: str) -> bool:
        return bool(re.search(r"\b(execute|place order|send order|open position)\b", message or "", re.IGNORECASE))

    def _parse_bool(self, value: Any, default: bool = False) -> bool:
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

    def _is_plan_mode_enabled(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        """
        Plan mode is opt-in: only enabled when explicitly set.
        """
        if not isinstance(tool_states, dict):
            return False
        raw = tool_states.get("plan_mode")
        if raw is None:
            return False
        if isinstance(raw, str):
            return raw.strip().lower() not in {"0", "false", "off", "no"}
        return bool(raw)

    def _build_plan_phase(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        tool_states: Optional[Dict[str, Any]],
    ) -> AgentPlan:
        return self.reasoning_orchestrator.build_plan(
            user_message=user_message,
            history=history,
            tool_states=tool_states,
        )

    async def _maybe_execute_order(
        self,
        plan: AgentPlan,
        user_message: str,
        user_context: Optional[Dict[str, Any]],
        tool_states: Optional[Dict[str, Any]],
    ) -> Optional[ToolResult]:
        tool_states = tool_states or {}
        user_context = user_context or {}

        policy_mode = str(tool_states.get("policy_mode", "advice_only")).lower()
        execution_enabled = bool(tool_states.get("execution"))
        # Strict auto-execute requires both enabled AND policy=auto_exec
        can_auto_execute = policy_mode == "auto_exec" and execution_enabled

        # 1. Check intent first
        if not plan.context.requested_execution:
            return None
        
        # 2. Check for explicit phrase to avoid accidental triggers on discussion
        if not self._has_explicit_execute_phrase(user_message):
            return None

        # 3. Validate Context & Parameters
        user_address = user_context.get("user_address")
        if not user_address:
            # We return a failed result so the agent knows why it couldn't proceed
            return ToolResult(
                name="place_order",
                args={},
                ok=False,
                error="Missing user_address in user_context.",
                data={"error": "Missing user_address in user_context."},
            )

        if not plan.context.symbol or not plan.context.side or not plan.context.amount_usd:
            return ToolResult(
                name="place_order",
                args={},
                ok=False,
                error="Execution skipped: missing symbol/side/amount.",
                data={"error": "Execution skipped: missing symbol/side/amount."},
            )

        exchange = str(tool_states.get("execution_exchange", "simulation")).lower()
        max_notional = float(tool_states.get("max_notional_usd", 5000) or 5000)
        max_leverage = int(tool_states.get("max_leverage", 50) or 50)

        if (plan.context.amount_usd or 0) > max_notional:
            return ToolResult(
                name="place_order",
                args={},
                ok=False,
                error=f"Blocked by max_notional_usd ({max_notional}).",
                data={"error": f"Blocked by max_notional_usd ({max_notional})."},
            )
        if (plan.context.leverage or 1) > max_leverage:
            return ToolResult(
                name="place_order",
                args={},
                ok=False,
                error=f"Blocked by max_leverage ({max_leverage}x).",
                data={"error": f"Blocked by max_leverage ({max_leverage}x)."},
            )

        # 4. Construct Order Arguments
        order_args: Dict[str, Any] = {
            "user_address": user_address,
            "symbol": plan.context.symbol,
            "side": plan.context.side,
            "amount_usd": float(plan.context.amount_usd),
            "leverage": int(plan.context.leverage or 1),
            "order_type": plan.context.order_type if plan.context.order_type in {"market", "limit", "stop_limit"} else "market",
            "exchange": exchange,
        }
        if plan.context.limit_price:
            order_args["price"] = float(plan.context.limit_price)
        if plan.context.stop_price:
            order_args["stop_price"] = float(plan.context.stop_price)
        if plan.context.tp is not None:
            order_args["tp"] = float(plan.context.tp)
        if plan.context.sl is not None:
            order_args["sl"] = float(plan.context.sl)

        # 5. Decide: Execute or Propose?
        if can_auto_execute:
            start = time.perf_counter()
            data = await ExecutionAdapter.place_order(**order_args)
            latency = int((time.perf_counter() - start) * 1000)
            has_error = isinstance(data, dict) and bool(data.get("error"))
            return ToolResult(
                name="place_order",
                args=order_args,
                ok=not has_error,
                error=data.get("error") if has_error else None,
                data=data,
                latency_ms=latency
            )
        else:
            # HITL Flow: Return a proposal result
            # The frontend will render this as an approval card.
            return ToolResult(
                name="place_order",
                args=order_args,
                ok=True,
                error=None,
                data={
                    "status": "proposal", 
                    "order": order_args,
                    "reason": "Human approval required (HITL)."
                },
                latency_ms=0
            )


    async def _run_tool(self, call: ToolCall, tool_states: Optional[Dict[str, Any]] = None) -> ToolResult:
        self.tool_orchestrator.set_registry(self._registry)
        return await self.tool_orchestrator.run_tool(call, tool_states=tool_states)

    def _tool_accepts_kwarg(self, tool_name: str, arg_name: str) -> bool:
        tool_fn = self._registry.get(tool_name)
        if tool_fn is None:
            return False
        try:
            signature = inspect.signature(tool_fn)
        except Exception:
            return False
        if arg_name in signature.parameters:
            return True
        return any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

    def _tool_call_key(self, call: ToolCall) -> Tuple[str, str]:
        return call.name, json.dumps(call.args, ensure_ascii=False, sort_keys=True, default=str)

    def _inject_user_address_for_tool(
        self,
        call: ToolCall,
        user_context: Optional[Dict[str, Any]],
    ) -> None:
        if call.name not in USER_ADDRESS_REQUIRED_TOOLS:
            return
        args = dict(call.args or {})
        if args.get("user_address"):
            call.args = args
            return
        user_context = user_context or {}
        user_address = str(
            user_context.get("user_address")
            or user_context.get("wallet_address")
            or user_context.get("address")
            or ""
        ).strip()
        if user_address:
            args["user_address"] = user_address
            call.args = args

    def _normalize_symbol(self, raw: Any) -> Optional[str]:
        if raw is None:
            return None
        value = str(raw).strip().upper().replace("/", "-").replace("_", "-")
        if not value:
            return None
        if "-" in value:
            base, quote = value.split("-", 1)
            if not base:
                return None
            if quote in {"USD", "USDT"}:
                return f"{base}-USD"
            return f"{base}-{quote}"
        if value.endswith("USDT") and len(value) > 4:
            return f"{value[:-4]}-USD"
        if value.endswith("USD") and len(value) > 3:
            return f"{value[:-3]}-USD"
        return f"{value}-USD"

    def _call_references_symbol(self, call: ToolCall) -> bool:
        args = call.args or {}
        if not isinstance(args, dict):
            return False
        return any(k in args for k in ("symbol", "target_symbol"))

    def _ensure_symbol_sync_tool(
        self,
        plan: AgentPlan,
        tool_states: Optional[Dict[str, Any]],
    ) -> None:
        """
        Keep tool execution flexible:
        when requested symbol differs from active chip symbol, prepend `set_symbol`
        before any symbol-scoped tool call.
        """
        tool_states = tool_states or {}
        requested_symbol = self._normalize_symbol(plan.context.symbol)
        active_symbol = self._normalize_symbol(
            tool_states.get("market_symbol") or tool_states.get("market") or tool_states.get("market_display")
        )
        if not requested_symbol or not active_symbol or requested_symbol == active_symbol:
            return

        symbol_calls = [c for c in plan.tool_calls if c.name != "set_symbol" and self._call_references_symbol(c)]
        if not symbol_calls:
            return

        if not bool(tool_states.get("write")):
            warning = (
                f"Requested symbol differs from active chart ({active_symbol} -> {requested_symbol}). "
                "Enable 'Allow Write' to sync chart symbol automatically."
            )
            if warning not in plan.warnings:
                plan.warnings.append(warning)
            return

        desired_call = ToolCall(
            name="set_symbol",
            args={"symbol": active_symbol, "target_symbol": requested_symbol},
            reason=f"Auto-sync chart symbol from {active_symbol} to {requested_symbol} before symbol-scoped tools.",
        )
        desired_key = self._tool_call_key(desired_call)

        existing_idx = None
        for idx, call in enumerate(plan.tool_calls):
            if call.name != "set_symbol":
                continue
            current_target = self._normalize_symbol((call.args or {}).get("target_symbol") or (call.args or {}).get("symbol"))
            if current_target == requested_symbol:
                existing_idx = idx
                break

        if existing_idx is None:
            plan.tool_calls.insert(0, desired_call)
            return

        existing_call = plan.tool_calls[existing_idx]
        if self._tool_call_key(existing_call) != desired_key:
            plan.tool_calls[existing_idx] = desired_call
        if existing_idx != 0:
            call = plan.tool_calls.pop(existing_idx)
            plan.tool_calls.insert(0, call)

    def _has_result(self, tool_results: List[ToolResult], tool_name: str) -> bool:
        return any(item.name == tool_name for item in tool_results)

    def _is_result_ok(self, result: ToolResult) -> bool:
        if not result.ok:
            return False
        if isinstance(result.data, dict) and result.data.get("error"):
            return False
        return True

    def _is_retryable_tool_result(self, result: ToolResult) -> bool:
        if result.ok:
            return False
        error_text = str(result.error or "").strip().lower()
        if not error_text:
            return True

        non_retryable_markers = (
            "unknown tool",
            "requires write mode",
            "allow write",
            "missing required",
            "validation error",
            "invalid argument",
            "blocked by",
            "not supported",
            "unsupported",
        )
        return not any(marker in error_text for marker in non_retryable_markers)

    def _normalize_state_symbol(self, value: Any) -> str:
        raw = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
        if not raw:
            return ""
        if "-" in raw:
            base, quote = raw.split("-", 1)
            if quote in {"USD", "USDT"}:
                return f"{base}-USD"
            return f"{base}-{quote}"
        if len(raw) == 6 and raw[:3] in {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD"} and raw[3:] in {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD"}:
            return f"{raw[:3]}-{raw[3:]}"
        if raw.endswith("USDT") and len(raw) > 4:
            return f"{raw[:-4]}-USD"
        if raw.endswith("USD") and len(raw) > 3:
            return f"{raw[:-3]}-USD"
        if raw.isalpha() and 2 <= len(raw) <= 12:
            return f"{raw}-USD"
        return raw

    def _normalize_state_timeframe(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        mapping = {
            "1M": "1m",
            "3M": "3m",
            "5M": "5m",
            "15M": "15m",
            "30M": "30m",
            "1H": "1H",
            "4H": "4H",
            "1D": "1D",
            "1W": "1W",
        }
        return mapping.get(text, text)

    def _check_tradingview_write_precision(
        self,
        result: ToolResult,
        tool_states: Optional[Dict[str, Any]],
    ) -> Tuple[str, str]:
        data = result.data if isinstance(result.data, dict) else {}
        strict = self._parse_bool((tool_states or {}).get("strict_write_verification"), default=True)

        command_status = str(data.get("status") or "").strip().lower()
        command_result = data.get("command_result") if isinstance(data.get("command_result"), dict) else {}
        command_result_status = str(command_result.get("status") or "").strip().lower()
        expected_state = data.get("expected_state") if isinstance(data.get("expected_state"), dict) else {}
        state_evidence = data.get("state_evidence") if isinstance(data.get("state_evidence"), dict) else {}

        if command_status not in {"completed", "success", "ok", "done"}:
            return "fail", f"write command status={command_status or 'unknown'}"
        if command_result_status and command_result_status not in {"completed", "success", "ok", "done"}:
            return "fail", f"write command result_status={command_result_status}"

        if not expected_state:
            return "pass", "write command completed"

        missing: List[str] = []
        mismatch: List[str] = []
        for key, expected_value in expected_state.items():
            if key not in state_evidence:
                missing.append(key)
                continue
            actual_value = state_evidence.get(key)
            if key == "symbol":
                if self._normalize_state_symbol(actual_value) != self._normalize_state_symbol(expected_value):
                    mismatch.append(key)
            elif key == "timeframe":
                if self._normalize_state_timeframe(actual_value) != self._normalize_state_timeframe(expected_value):
                    mismatch.append(key)
            else:
                if str(actual_value or "").strip().lower() != str(expected_value or "").strip().lower():
                    mismatch.append(key)

        if not missing and not mismatch:
            return "pass", "write state verified"
        if strict:
            parts: List[str] = []
            if missing:
                parts.append("missing=" + ",".join(missing))
            if mismatch:
                parts.append("mismatch=" + ",".join(mismatch))
            return "fail", "write verification failed (" + "; ".join(parts) + ")"
        return "warn", "write evidence incomplete"

    def _check_tool_result_quality(
        self,
        result: ToolResult,
        *,
        tool_mode: str = "read",
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """
        Explicit post-await quality check before reasoning synthesis.
        Returns (status, reason), where status in {"pass", "warn", "fail"}.
        """
        if not result.ok:
            return "fail", str(result.error or "tool returned error")

        data = result.data
        if isinstance(data, dict):
            if data.get("error"):
                return "fail", str(data.get("error"))

            status_value = str(data.get("status") or "").strip().lower()
            if status_value in {"error", "failed", "fail"}:
                return "fail", f"tool status={status_value}"

            warning_code = str(data.get("warning_code") or "").strip().lower()
            if warning_code:
                return "warn", f"warning_code={warning_code}"

            if "results_count" in data:
                try:
                    count = int(data.get("results_count") or 0)
                except Exception:
                    count = 0
                if count <= 0:
                    return "warn", "no results returned"

            if tool_mode == "write" and str(data.get("transport") or "").strip().lower() == "tradingview_command":
                return self._check_tradingview_write_precision(result, tool_states=tool_states)

        return "pass", "output usable"

    def _normalize_retry_attempt_cap(self, raw: Any, fallback: int) -> int:
        try:
            parsed = int(raw)
        except Exception:
            parsed = int(fallback)
        return max(1, min(parsed, 4))

    def _resolve_retry_attempt_cap(
        self,
        tool_name: str,
        tool_mode: str,
        tool_states: Optional[Dict[str, Any]],
        default_cap: int,
        read_cap: int,
        nav_cap: int,
        write_cap: int,
    ) -> int:
        tool_states = tool_states or {}
        cap = default_cap
        if tool_mode == "write":
            cap = write_cap
        elif tool_mode == "nav":
            cap = nav_cap
        elif tool_mode == "read":
            cap = read_cap

        overrides = tool_states.get("tool_retry_attempts")
        if isinstance(overrides, dict):
            exact = overrides.get(tool_name)
            short = overrides.get(tool_name.split(".")[-1]) if "." in tool_name else None
            selected = exact if exact is not None else short
            if selected is not None:
                return self._normalize_retry_attempt_cap(selected, cap)

        return cap

    def _infer_asset_type_from_symbol(self, symbol: Optional[str]) -> str:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return "crypto"
        if "-" not in normalized:
            return "crypto"
        base, quote = normalized.split("-", 1)
        if base in FIAT_CODES:
            return "rwa"
        if quote in FIAT_CODES and quote not in {"USD", "USDT"}:
            return "rwa"
        return "crypto"

    def _symbol_to_tool_symbol(self, symbol: Optional[str], asset_type: str) -> Optional[str]:
        normalized = self._normalize_symbol(symbol)
        if not normalized:
            return None
        if "-" not in normalized:
            return normalized
        base, quote = normalized.split("-", 1)
        if asset_type == "crypto" and quote in {"USD", "USDT"} and base not in FIAT_CODES:
            return base
        return f"{base}-{quote}"

    def _is_web_observation_enabled(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        tool_states = tool_states or {}
        raw = tool_states.get("web_observation_enabled")
        if raw is None:
            provider = str(tool_states.get("runtime_model_provider") or "").strip().lower()
            model_id = str(tool_states.get("runtime_model_id") or "").strip().lower()
            if provider in {"openrouter"}:
                return True
            return False
        return self._parse_bool(raw, default=False)

    def _resolve_web_observation_mode(self, tool_states: Optional[Dict[str, Any]]) -> str:
        tool_states = tool_states or {}
        raw_mode = str(tool_states.get("web_observation_mode") or "").strip().lower()
        if raw_mode in {"quality", "speed", "budget"}:
            return raw_mode
        return "quality"

    def _is_memory_enabled(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        tool_states = tool_states or {}
        return self._parse_bool(tool_states.get("memory_enabled"), default=False)

    def _is_knowledge_enabled(self, tool_states: Optional[Dict[str, Any]]) -> bool:
        tool_states = tool_states or {}
        return self._parse_bool(tool_states.get("knowledge_enabled"), default=False)

    def _resolve_flow_mode(self, tool_states: Optional[Dict[str, Any]]) -> str:
        # Runtime architecture is synchronous-by-design:
        # one action is completed and observed before the next action starts.
        # Legacy async mode switches are intentionally ignored.
        return "sync"

    def _resolve_rag_mode(self, tool_states: Optional[Dict[str, Any]]) -> str:
        """
        RAG behavior:
        - secondary (default): no runtime prefetch, allow upper layer fallback.
        - primary: runtime prefetch/follow-up allowed.
        - off: disable runtime retrieval.
        """
        tool_states = tool_states or {}
        raw = str(
            tool_states.get("rag_mode")
            or tool_states.get("knowledge_mode")
            or tool_states.get("knowledge_strategy")
            or "secondary"
        ).strip().lower()
        if raw in {"primary", "eager", "always"}:
            return "primary"
        if raw in {"off", "disabled", "none"}:
            return "off"
        return "secondary"

    def _resolve_memory_user_id(
        self,
        tool_states: Optional[Dict[str, Any]],
        user_context: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        tool_states = tool_states or {}
        user_context = user_context or {}
        explicit = (
            tool_states.get("memory_user_id")
            or user_context.get("memory_user_id")
            or user_context.get("user_address")
            or user_context.get("user_id")
        )
        if explicit is None:
            return None
        value = str(explicit).strip()
        return value or None

    def _resolve_memory_top_k(self, tool_states: Optional[Dict[str, Any]]) -> int:
        tool_states = tool_states or {}
        try:
            top_k = int(tool_states.get("memory_top_k", 5) or 5)
        except Exception:
            top_k = 5
        return max(1, min(top_k, 12))

    def _resolve_knowledge_top_k(self, tool_states: Optional[Dict[str, Any]]) -> int:
        tool_states = tool_states or {}
        try:
            top_k = int(tool_states.get("knowledge_top_k", 4) or 4)
        except Exception:
            top_k = 4
        return max(1, min(top_k, 8))

    def _resolve_knowledge_category(self, tool_states: Optional[Dict[str, Any]]) -> Optional[str]:
        tool_states = tool_states or {}
        raw = tool_states.get("knowledge_category")
        if raw is None:
            return None
        value = str(raw).strip().lower()
        if value in {"identity", "drawing", "trade", "market", "psychology", "user", "experience"}:
            return value
        return None

    def _has_success_result(self, tool_results: List[ToolResult], tool_name: str) -> bool:
        return any(item.name == tool_name and self._is_result_ok(item) for item in tool_results)

    def _should_prefetch_knowledge(self, user_message: str) -> bool:
        text = (user_message or "").strip().lower()
        if len(text) < 3:
            return False
        greetings = {"hi", "hello", "hey", "gm", "good morning", "good evening"}
        if text in greetings:
            return False
        return True

    def _infer_followup_calls(
        self,
        user_message: str,
        plan: AgentPlan,
        tool_results: List[ToolResult],
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> List[ToolCall]:
        """
        Adaptive tool expansion:
        after initial calls, add missing related tools when context is still incomplete.
        """
        followups: List[ToolCall] = []
        message = (user_message or "").lower()
        symbol = plan.context.symbol
        timeframe = plan.context.timeframe or "1H"
        if not symbol:
            return followups
        asset_type = self._infer_asset_type_from_symbol(symbol)
        tool_symbol = self._symbol_to_tool_symbol(symbol, asset_type) or symbol

        wants_rsi = "rsi" in message
        wants_indicator_context = wants_rsi or "indicator" in message or "technical" in message
        wants_high_low_levels = any(term in message for term in ("high low", "high/low", "support", "resistance", "s/r"))
        wants_orderbook = "orderbook" in message or "order book" in message or "depth" in message
        wants_funding = "funding" in message
        wants_sentiment_context = any(
            term in message for term in ("sentiment", "twitter", "x.com", "x ", "crowd", "social")
        )
        if asset_type != "crypto":
            if wants_orderbook:
                warning = "Orderbook depth is only available for crypto markets."
                if warning not in plan.warnings:
                    plan.warnings.append(warning)
            if wants_funding:
                warning = "Funding-rate context is unavailable for this non-crypto market."
                if warning not in plan.warnings:
                    plan.warnings.append(warning)

        if wants_indicator_context:
            if not self._has_result(tool_results, "get_active_indicators"):
                followups.append(
                    ToolCall(
                        name="get_active_indicators",
                        args={"symbol": symbol, "timeframe": timeframe},
                        reason="Follow-up: read active indicators currently loaded on chart.",
                    )
                )
            if wants_rsi and not self._has_result(tool_results, "get_indicators"):
                followups.append(
                    ToolCall(
                        name="get_indicators",
                        args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                        reason="Follow-up: fetch indicator values (including RSI).",
                    )
                )

        if wants_high_low_levels and not self._has_result(tool_results, "get_high_low_levels"):
            followups.append(
                ToolCall(
                    name="get_high_low_levels",
                    args={"symbol": tool_symbol, "timeframe": timeframe, "lookback": 7, "asset_type": asset_type},
                    reason="Follow-up: compute rolling support/resistance high-low levels.",
                )
            )

        if asset_type == "crypto" and wants_orderbook and not self._has_result(tool_results, "get_orderbook"):
            followups.append(
                ToolCall(
                    name="get_orderbook",
                    args={"symbol": tool_symbol, "asset_type": asset_type},
                    reason="Follow-up: gather market depth evidence.",
                )
            )
        if asset_type == "crypto" and wants_funding and not self._has_result(tool_results, "get_funding_rate"):
            followups.append(
                ToolCall(
                    name="get_funding_rate",
                    args={"symbol": tool_symbol, "asset_type": asset_type},
                    reason="Follow-up: gather perp funding context.",
                )
            )

        web_observation_enabled = self._is_web_observation_enabled(tool_states)
        web_mode = self._resolve_web_observation_mode(tool_states)
        looks_like_analysis = (
            plan.intent == "analysis"
            or any(
                term in message
                for term in (
                    "analyze",
                    "analysis",
                    "technical",
                    "trend",
                    "setup",
                    "risk",
                    "market",
                    "observasi",
                    "observe",
                )
            )
        )
        if web_observation_enabled and looks_like_analysis:
            if not self._has_result(tool_results, "search_news"):
                followups.append(
                    ToolCall(
                        name="search_news",
                        args={"query": f"{symbol} latest market news and catalysts", "mode": web_mode},
                        reason="Follow-up observation: enrich analysis with recent web/news context.",
                    )
                )
            if (
                asset_type == "crypto"
                and (wants_sentiment_context or plan.context.requested_sentiment)
                and not self._has_result(tool_results, "search_sentiment")
            ):
                followups.append(
                    ToolCall(
                        name="search_sentiment",
                        args={"symbol": tool_symbol, "mode": web_mode},
                        reason="Follow-up observation: cross-check social sentiment for the symbol.",
                    )
                )

        knowledge_enabled = self._is_knowledge_enabled(tool_states)
        rag_mode = self._resolve_rag_mode(tool_states)
        if (
            knowledge_enabled
            and rag_mode == "primary"
            and looks_like_analysis
            and not self._has_success_result(tool_results, "search_knowledge_base")
        ):
            knowledge_args: Dict[str, Any] = {
                "query": f"{symbol} {timeframe} trading analysis playbook and risk management",
                "top_k": self._resolve_knowledge_top_k(tool_states),
            }
            category = self._resolve_knowledge_category(tool_states)
            if category:
                knowledge_args["category"] = category
            followups.append(
                ToolCall(
                    name="search_knowledge_base",
                    args=knowledge_args,
                    reason="Follow-up observation: retrieve relevant internal trading knowledge context.",
                )
            )

        # If all current tool calls failed, force a lightweight fallback.
        if tool_results and all(not self._is_result_ok(item) for item in tool_results):
            if not self._has_result(tool_results, "get_price"):
                followups.append(
                    ToolCall(
                        name="get_price",
                        args={"symbol": tool_symbol, "asset_type": asset_type},
                        reason="Fallback: fetch latest price after failed upstream calls.",
                    )
                )
            if web_observation_enabled and not self._has_result(tool_results, "search_news"):
                followups.append(
                    ToolCall(
                        name="search_news",
                        args={"query": f"{symbol} urgent market updates", "mode": "speed"},
                        reason="Fallback: use web search when primary connectors fail.",
                    )
                )

        return followups

    def _truncate(self, value: Any) -> str:
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            payload = str(value)
        if len(payload) <= self._max_output_chars:
            return payload
        return payload[: self._max_output_chars] + "...(truncated)"

    def _coerce_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _knowledge_signal_rank(self, signal: str) -> int:
        ranking = {
            "strong": 5,
            "medium": 4,
            "weak": 3,
            "none": 2,
            "error": 1,
            "not_used": 0,
        }
        return ranking.get(signal, 0)

    def _classify_knowledge_signal(self, result: ToolResult) -> Dict[str, Any]:
        data = result.data if isinstance(result.data, dict) else {}
        if not result.ok:
            return {
                "signal": "error",
                "reason": str(result.error or "knowledge lookup failed"),
                "max_score": None,
                "results_count": 0,
                "warning_code": None,
                "sources": [],
            }

        warning_code = str(data.get("warning_code") or "").strip().lower() or None
        results = data.get("results") if isinstance(data.get("results"), list) else []
        results_count = int(data.get("results_count", len(results)) or 0)
        max_score = 0.0
        sources: List[str] = []

        for item in results[:5]:
            if not isinstance(item, dict):
                continue
            score = self._coerce_float(item.get("score"))
            if score is not None:
                max_score = max(max_score, score)
            title = str(item.get("title") or "").strip()
            category = str(item.get("category") or "").strip()
            subcategory = str(item.get("subcategory") or "").strip()
            source_line = title or "untitled"
            if category:
                source_line += f" ({category}"
                if subcategory:
                    source_line += f"/{subcategory}"
                source_line += ")"
            if source_line not in sources:
                sources.append(source_line)

        if warning_code == "zero_similarity":
            signal = "weak"
        elif results_count <= 0:
            signal = "none"
        elif max_score <= 0.0:
            signal = "weak"
        elif max_score < 0.2:
            signal = "weak"
        elif max_score < 0.45:
            signal = "medium"
        else:
            signal = "strong"

        reason_map = {
            "strong": "RAG evidence is relevant and can be used as supporting framework.",
            "medium": "RAG evidence is moderately relevant; use with caution and cross-check.",
            "weak": "RAG evidence quality is weak; do not rely on it for decisive claims.",
            "none": "No relevant RAG matches found.",
            "error": "RAG lookup failed.",
        }

        return {
            "signal": signal,
            "reason": reason_map.get(signal, "RAG signal unavailable."),
            "max_score": round(max_score, 4) if results_count > 0 else None,
            "results_count": results_count,
            "warning_code": warning_code,
            "sources": sources[:3],
        }

    def _summarize_knowledge_signal(self, tool_results: List[ToolResult]) -> Dict[str, Any]:
        knowledge_results = [item for item in tool_results if item.name == "search_knowledge_base"]
        if not knowledge_results:
            return {
                "signal": "not_used",
                "reason": "RAG was not called in this runtime cycle.",
                "max_score": None,
                "results_count": 0,
                "warning_code": None,
                "sources": [],
            }

        summaries = [self._classify_knowledge_signal(item) for item in knowledge_results]
        selected = max(summaries, key=lambda item: self._knowledge_signal_rank(str(item.get("signal") or "")))
        return selected

    def _render_context(self, plan: AgentPlan, tool_results: List[ToolResult]) -> str:
        lines: List[str] = []
        lines.append("AGENTIC_TRADING_RUNTIME_CONTEXT")
        lines.append(f"intent={plan.intent}")
        lines.append(f"symbol={plan.context.symbol or 'none'}")
        lines.append(f"timeframe={plan.context.timeframe}")
        lines.append(f"requested_execution={plan.context.requested_execution}")
        lines.append("")

        if plan.warnings:
            lines.append("warnings:")
            for item in plan.warnings:
                lines.append(f"- {item}")
            lines.append("")

        if plan.blocks:
            lines.append("blocks:")
            for item in plan.blocks:
                lines.append(f"- {item}")
            lines.append("")

        if plan.tool_calls:
            lines.append("planned_tools:")
            for idx, call in enumerate(plan.tool_calls, start=1):
                lines.append(f"{idx}. {call.name} args={call.args} reason={call.reason}")
            lines.append("")

        if tool_results:
            lines.append("tool_outputs:")
            for idx, result in enumerate(tool_results, start=1):
                status = "ok" if result.ok else "error"
                lines.append(
                    f"{idx}. {result.name} [{status}] latency_ms={result.latency_ms} args={result.args}"
                )
                lines.append(self._truncate(result.data))
                check_state, check_reason = self._check_tool_result_quality(result)
                lines.append(f"check={check_state} reason={check_reason}")
                lines.append("")
        else:
            lines.append("tool_outputs: none")

        knowledge_signal = self._summarize_knowledge_signal(tool_results)
        lines.append("knowledge_evidence:")
        lines.append(f"- signal={knowledge_signal.get('signal')}")
        lines.append(f"- reason={knowledge_signal.get('reason')}")
        lines.append(f"- results_count={knowledge_signal.get('results_count')}")
        lines.append(f"- max_score={knowledge_signal.get('max_score')}")
        lines.append(f"- warning_code={knowledge_signal.get('warning_code') or 'none'}")
        source_list = knowledge_signal.get("sources") or []
        if source_list:
            lines.append("- sources:")
            for source in source_list:
                lines.append(f"  - {source}")
        else:
            lines.append("- sources: none")
        lines.append("")

        lines.append("reasoning_policy:")
        lines.append("- Follow Think -> Act -> Observe discipline for each decision.")
        lines.append("- Treat live market/news tools as time-sensitive evidence.")
        lines.append("- Treat knowledge base as framework evidence, not live price evidence.")
        lines.append(
            "- If knowledge signal is weak/none/error/not_used, avoid definitive knowledge-based claims and explicitly state limitation."
        )
        lines.append("")

        lines.append(
            "instruction: Use tool outputs as evidence. If blocked, refuse execution and provide safer next steps. "
            "If a symbol has technical/news tool errors, avoid precise numeric entry/SL/TP/invalidation for that symbol."
        )
        return "\n".join(lines).strip()

    async def prepare(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        tool_states: Optional[Dict[str, Any]] = None,
        user_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tool_states = tool_states or {}
        rag_mode = self._resolve_rag_mode(tool_states)
        phases: List[Dict[str, Any]] = []

        def phase(
            name: str,
            status: str = "done",
            detail: str = "",
            meta: Optional[Dict[str, Any]] = None,
        ) -> None:
            entry: Dict[str, Any] = {
                "name": name,
                "status": status,
                "detail": detail,
            }
            if meta:
                entry["meta"] = meta
            phases.append(entry)

        def has_phase(name: str) -> bool:
            return any(item.get("name") == name for item in phases)

        def ensure_phase(
            name: str,
            status: str = "skipped",
            detail: str = "Not triggered for this request.",
            meta: Optional[Dict[str, Any]] = None,
        ) -> None:
            if has_phase(name):
                return
            phase(name, status, detail, meta)

        memory_prefetched: List[ToolResult] = []
        knowledge_prefetched: List[ToolResult] = []
        memory_enabled = self._is_memory_enabled(tool_states)
        if memory_enabled:
            memory_user_id = self._resolve_memory_user_id(tool_states=tool_states, user_context=user_context)
            memory_top_k = self._resolve_memory_top_k(tool_states=tool_states)
            phase(
                "memory_think",
                "done",
                "Memory enabled: checking whether relevant prior context should be recalled.",
                {"enabled": True, "top_k": memory_top_k},
            )
            if not memory_user_id:
                phase(
                    "memory_act",
                    "skipped",
                    "Memory recall skipped: user id is missing.",
                    {"enabled": True},
                )
                phase(
                    "memory_observe",
                    "skipped",
                    "No memory observation available.",
                    {"enabled": True},
                )
            elif "search_memory" not in self._registry:
                phase(
                    "memory_act",
                    "skipped",
                    "Memory recall skipped: search_memory tool not registered.",
                    {"enabled": True, "user_id": memory_user_id},
                )
                phase(
                    "memory_observe",
                    "skipped",
                    "No memory observation available.",
                    {"enabled": True, "user_id": memory_user_id},
                )
            else:
                recall_call = ToolCall(
                    name="search_memory",
                    args={"user_id": memory_user_id, "query": user_message, "limit": memory_top_k},
                    reason="Recall relevant prior user memory before analysis.",
                )
                phase(
                    "memory_act",
                    "running",
                    "Recalling relevant memory context.",
                    {"enabled": True, "tool": "search_memory", "user_id": memory_user_id, "top_k": memory_top_k},
                )
                recall_result = await self._run_tool(recall_call, tool_states=tool_states)
                memory_prefetched.append(recall_result)
                phase(
                    "memory_act",
                    "done" if recall_result.ok else "error",
                    "Memory recall completed." if recall_result.ok else "Memory recall failed.",
                    {
                        "enabled": True,
                        "tool": "search_memory",
                        "user_id": memory_user_id,
                        "ok": recall_result.ok,
                        "latency_ms": recall_result.latency_ms,
                    },
                )
                phase(
                    "memory_observe",
                    "done" if recall_result.ok else "error",
                    (
                        "Memory observation available for synthesis."
                        if recall_result.ok
                        else "Memory observation unavailable due to recall error."
                    ),
                    {
                        "enabled": True,
                        "tool": "search_memory",
                        "user_id": memory_user_id,
                        "ok": recall_result.ok,
                    },
                )

        knowledge_enabled = self._is_knowledge_enabled(tool_states)
        if knowledge_enabled and rag_mode == "primary":
            knowledge_top_k = self._resolve_knowledge_top_k(tool_states=tool_states)
            knowledge_category = self._resolve_knowledge_category(tool_states=tool_states)
            phase(
                "knowledge_think",
                "done",
                "Knowledge retrieval enabled: evaluating whether RAG context should be prefetched.",
                {"enabled": True, "top_k": knowledge_top_k, "category": knowledge_category},
            )
            if not self._should_prefetch_knowledge(user_message):
                phase(
                    "knowledge_act",
                    "skipped",
                    "Knowledge prefetch skipped: message is too short or smalltalk-like.",
                    {"enabled": True},
                )
                phase(
                    "knowledge_observe",
                    "skipped",
                    "No knowledge observation available.",
                    {"enabled": True},
                )
            elif "search_knowledge_base" not in self._registry:
                phase(
                    "knowledge_act",
                    "skipped",
                    "Knowledge prefetch skipped: search_knowledge_base tool not registered.",
                    {"enabled": True},
                )
                phase(
                    "knowledge_observe",
                    "skipped",
                    "No knowledge observation available.",
                    {"enabled": True},
                )
            else:
                rag_args: Dict[str, Any] = {"query": user_message, "top_k": knowledge_top_k}
                if knowledge_category:
                    rag_args["category"] = knowledge_category
                rag_call = ToolCall(
                    name="search_knowledge_base",
                    args=rag_args,
                    reason="Prefetch internal knowledge evidence before planning/execution.",
                )
                phase(
                    "knowledge_act",
                    "running",
                    "Retrieving relevant internal knowledge context.",
                    {"enabled": True, "tool": "search_knowledge_base", "top_k": knowledge_top_k, "category": knowledge_category},
                )
                rag_result = await self._run_tool(rag_call, tool_states=tool_states)
                knowledge_prefetched.append(rag_result)
                phase(
                    "knowledge_act",
                    "done" if rag_result.ok else "error",
                    "Knowledge retrieval completed." if rag_result.ok else "Knowledge retrieval failed.",
                    {
                        "enabled": True,
                        "tool": "search_knowledge_base",
                        "ok": rag_result.ok,
                        "latency_ms": rag_result.latency_ms,
                    },
                )
                phase(
                    "knowledge_observe",
                    "done" if rag_result.ok else "error",
                    (
                        "Knowledge evidence is available for synthesis."
                        if rag_result.ok
                        else "Knowledge evidence unavailable due to retrieval error."
                    ),
                    {
                        "enabled": True,
                        "tool": "search_knowledge_base",
                        "ok": rag_result.ok,
                    },
                )
        elif knowledge_enabled and rag_mode == "secondary":
            phase(
                "knowledge_think",
                "done",
                "RAG strategy is secondary: skip runtime prefetch; defer to fallback.",
                {"enabled": True, "rag_mode": "secondary"},
            )
            phase(
                "knowledge_act",
                "skipped",
                "No runtime knowledge retrieval in secondary mode.",
                {"enabled": True, "rag_mode": "secondary"},
            )
            phase(
                "knowledge_observe",
                "skipped",
                "No knowledge observation in secondary mode.",
                {"enabled": True, "rag_mode": "secondary"},
            )

        plan_mode_enabled = self._is_plan_mode_enabled(tool_states)
        if not plan_mode_enabled:
            fallback_timeframe = "1H"
            raw_tf = tool_states.get("timeframe")
            if isinstance(raw_tf, str) and raw_tf.strip():
                fallback_timeframe = raw_tf.strip()
            elif isinstance(raw_tf, list) and raw_tf:
                first_tf = raw_tf[0]
                if isinstance(first_tf, str) and first_tf.strip():
                    fallback_timeframe = first_tf.strip()

            plan = AgentPlan(
                intent="analysis",
                context=PlanContext(timeframe=fallback_timeframe),
            )
            phase(
                "plan_start",
                "skipped",
                "Plan mode disabled. Skipping plan and tool execution.",
                {"plan_mode": False},
            )
            phase(
                "plan_ready",
                "skipped",
                "No plan generated because plan mode is disabled.",
                {"plan_mode": False, "tool_count": 0},
            )

            tool_results: List[ToolResult] = [*memory_prefetched, *knowledge_prefetched]
            runtime_context = self._render_context(plan=plan, tool_results=tool_results)
            phase(
                "runtime_ready",
                "done",
                f"Runtime context ready with {len(tool_results)} tool results (plan mode disabled).",
                {"tool_results": len(tool_results), "plan_mode": False, "memory_enabled": memory_enabled},
            )

            ensure_phase("memory_think")
            ensure_phase("memory_act")
            ensure_phase("memory_observe")
            ensure_phase("knowledge_think")
            ensure_phase("knowledge_act")
            ensure_phase("knowledge_observe")
            ensure_phase("tool_round_start")
            ensure_phase("tool_execution")
            ensure_phase("tool_check")
            ensure_phase("tool_retry_think")
            ensure_phase("tool_retry_scheduled")
            ensure_phase("tool_followup")
            ensure_phase("tool_round_complete")
            ensure_phase("execution_adapter")
            ensure_phase("runtime_ready")

            return {
                "plan": plan,
                "tool_results": tool_results,
                "runtime_context": runtime_context,
                "phases": phases,
            }

        strict_react = True  # Enforced synchronous ReAct: Think -> Act(1) -> Observe
        default_plan_loops = 1
        plan_max_iterations = int(tool_states.get("max_plan_iterations", default_plan_loops) or default_plan_loops)
        plan_max_iterations = max(1, min(plan_max_iterations, 5))

        phase(
            "plan_start",
            "running",
            "Plan: building execution/analysis plan.",
            {"tool": "planner", "stage": "plan", "strict_react": strict_react},
        )

        plan: AgentPlan
        plan_loop = 0
        while True:
            plan_loop += 1
            phase(
                "plan_think",
                "done",
                f"Plan loop {plan_loop}: Think about user intent and required tools.",
                {"tool": "planner", "stage": "think", "loop": plan_loop},
            )
            phase(
                "plan_act",
                "running",
                f"Plan loop {plan_loop}: Act by drafting candidate plan.",
                {"tool": "planner", "stage": "act", "loop": plan_loop},
            )
            plan = self._build_plan_phase(
                user_message=user_message,
                history=history,
                tool_states=tool_states,
            )
            phase(
                "plan_observe",
                "done",
                (
                    f"Plan loop {plan_loop}: Observe candidate plan "
                    f"(tools={len(plan.tool_calls)}, warnings={len(plan.warnings)}, blocks={len(plan.blocks)})."
                ),
                {
                    "tool": "planner",
                    "stage": "observe",
                    "loop": plan_loop,
                    "tool_count": len(plan.tool_calls),
                    "warning_count": len(plan.warnings),
                    "block_count": len(plan.blocks),
                },
            )
            need_replan = (
                plan_loop < plan_max_iterations
                and not plan.blocks
                and len(plan.tool_calls) == 0
                and bool((user_message or "").strip())
            )
            if not need_replan:
                break

        phase(
            "plan_ready",
            "done",
            f"Plan: intent={plan.intent}, tools={len(plan.tool_calls)}.",
            {
                "intent": plan.intent,
                "tool_count": len(plan.tool_calls),
                "tool": "planner",
                "stage": "plan",
                "plan_loops": plan_loop,
            },
        )
        self._ensure_symbol_sync_tool(plan, tool_states)
        if plan.tool_calls and plan.tool_calls[0].name == "set_symbol":
            phase(
                "plan_symbol_sync",
                "done",
                "Prepended set_symbol before symbol-scoped tools.",
                {
                    "tool": "set_symbol",
                    "target_symbol": (plan.tool_calls[0].args or {}).get("target_symbol"),
                    "stage": "plan",
                },
            )

        tool_results: List[ToolResult] = [*memory_prefetched, *knowledge_prefetched]
        if not plan.blocks:
            max_tool_calls = int((tool_states or {}).get("max_tool_calls", 10) or 10)
            max_tool_calls = max(1, min(max_tool_calls, 16))
            executed_keys: Set[Tuple[str, str]] = set()
            executed_actions = 0
            pending_calls: List[ToolCall] = []
            pending_keys: Set[Tuple[str, str]] = set()
            retry_attempts: Dict[Tuple[str, str], int] = {}

            retry_failed_tools = self._parse_bool((tool_states or {}).get("retry_failed_tools"), default=True)
            max_retry_attempts = int((tool_states or {}).get("tool_retry_max_attempts", 2) or 2)
            max_retry_attempts = max(1, min(max_retry_attempts, 4))
            read_retry_max_attempts = self._normalize_retry_attempt_cap(
                (tool_states or {}).get("read_tool_retry_max_attempts", max_retry_attempts),
                max_retry_attempts,
            )
            nav_retry_max_attempts = self._normalize_retry_attempt_cap(
                (tool_states or {}).get("nav_tool_retry_max_attempts", max_retry_attempts),
                max_retry_attempts,
            )
            # Keep write tools conservative by default to avoid duplicate chart mutations.
            write_retry_max_attempts = self._normalize_retry_attempt_cap(
                (tool_states or {}).get("write_tool_retry_max_attempts", 1),
                1,
            )
            has_write_calls = any(self.tool_orchestrator.classify_tool_mode(call.name) == "write" for call in plan.tool_calls)
            write_txn_id = uuid.uuid4().hex if has_write_calls else None
            if write_txn_id:
                phase(
                    "write_txn_start",
                    "running",
                    "Initialized write transaction scope for TradingView mutation commands.",
                    {"write_txn_id": write_txn_id},
                )

            def enqueue_call(candidate: ToolCall) -> None:
                key = self._tool_call_key(candidate)
                if key in executed_keys or key in pending_keys:
                    return
                pending_calls.append(candidate)
                pending_keys.add(key)

            for initial_call in plan.tool_calls:
                enqueue_call(initial_call)

            loops = 0
            default_max_react_loops = max_tool_calls if strict_react else 3
            max_react_loops = int((tool_states or {}).get("max_react_iterations", default_max_react_loops) or default_max_react_loops)
            max_react_loops = max(1, min(max_react_loops, 32))

            while pending_calls and loops < max_react_loops and executed_actions < max_tool_calls:
                loops += 1
                phase(
                    "tool_round_start",
                    "running",
                    (
                        f"ReAct loop {loops}: {len(pending_calls)} tool(s) pending. "
                        f"{'Strict mode: execute exactly 1 action.' if strict_react else 'Batch mode enabled.'}"
                    ),
                    {"round": loops, "pending": len(pending_calls), "strict_react": strict_react},
                )

                if strict_react:
                    cycle_calls = [pending_calls.pop(0)]
                else:
                    cycle_calls = list(pending_calls)
                    pending_calls = []

                for call in cycle_calls:
                    self._inject_user_address_for_tool(call, user_context=user_context)
                    key = self._tool_call_key(call)
                    pending_keys.discard(key)
                    if key in executed_keys:
                        continue
                    if executed_actions >= max_tool_calls:
                        break

                    tool_mode = self.tool_orchestrator.classify_tool_mode(call.name)
                    if tool_mode == "write" and write_txn_id and self._tool_accepts_kwarg(call.name, "write_txn_id"):
                        call.args = dict(call.args or {})
                        call.args.setdefault("write_txn_id", write_txn_id)
                    max_attempts_for_call = self._resolve_retry_attempt_cap(
                        tool_name=call.name,
                        tool_mode=tool_mode,
                        tool_states=tool_states,
                        default_cap=max_retry_attempts,
                        read_cap=read_retry_max_attempts,
                        nav_cap=nav_retry_max_attempts,
                        write_cap=write_retry_max_attempts,
                    )
                    attempt_no = retry_attempts.get(key, 0) + 1
                    phase(
                        "tool_think",
                        "done",
                        f"Loop {loops}: Think whether `{call.name}` (attempt {attempt_no}/{max_attempts_for_call}) is the right next action.",
                        {
                            "tool": call.name,
                            "args": call.args,
                            "mode": tool_mode,
                            "stage": "think",
                            "loop": loops,
                            "attempt": attempt_no,
                            "max_attempts": max_attempts_for_call,
                        },
                    )
                    phase(
                        "tool_execution",
                        "running",
                        f"Loop {loops}: Act by calling `{call.name}` (attempt {attempt_no}/{max_attempts_for_call}).",
                        {
                            "tool": call.name,
                            "args": call.args,
                            "mode": tool_mode,
                            "stage": "act",
                            "loop": loops,
                            "attempt": attempt_no,
                            "max_attempts": max_attempts_for_call,
                        },
                    )
                    tool_results.append(await self._run_tool(call, tool_states=tool_states))
                    executed_actions += 1
                    last_result = tool_results[-1]
                    observe_detail = (
                        f"Loop {loops}: Observe `{last_result.name}` returned usable data."
                        if last_result.ok
                        else f"Loop {loops}: Observe `{last_result.name}` returned an error."
                    )
                    phase(
                        "tool_observe",
                        "done" if last_result.ok else "error",
                        observe_detail,
                        {
                            "tool": last_result.name,
                            "mode": tool_mode,
                            "ok": last_result.ok,
                            "latency_ms": last_result.latency_ms,
                            "stage": "observe",
                            "loop": loops,
                            "attempt": attempt_no,
                            "max_attempts": max_attempts_for_call,
                        },
                    )
                    check_state, check_reason = self._check_tool_result_quality(
                        last_result,
                        tool_mode=tool_mode,
                        tool_states=tool_states,
                    )
                    phase(
                        "tool_check",
                        "done" if check_state in {"pass", "warn"} else "error",
                        f"Loop {loops}: Check `{last_result.name}` => {check_state} ({check_reason}).",
                        {
                            "tool": last_result.name,
                            "mode": tool_mode,
                            "check": check_state,
                            "reason": check_reason,
                            "stage": "check",
                            "loop": loops,
                            "attempt": attempt_no,
                            "max_attempts": max_attempts_for_call,
                        },
                    )
                    if check_state == "fail" and last_result.ok:
                        last_result.ok = False
                        last_result.error = check_reason
                        if isinstance(last_result.data, dict):
                            last_result.data["error"] = check_reason
                    phase(
                        "tool_execution",
                        "done" if last_result.ok else "error",
                        f"Loop {loops}: Act result `{last_result.name}` {'ok' if last_result.ok else 'failed'}.",
                        {
                            "tool": last_result.name,
                            "mode": tool_mode,
                            "ok": last_result.ok,
                            "latency_ms": last_result.latency_ms,
                            "stage": "act",
                            "loop": loops,
                            "attempt": attempt_no,
                            "max_attempts": max_attempts_for_call,
                        },
                    )

                    scheduled_retry = False
                    if not last_result.ok and retry_failed_tools:
                        should_retry = self._is_retryable_tool_result(last_result)
                        has_budget = executed_actions < max_tool_calls
                        has_attempt_left = attempt_no < max_attempts_for_call
                        phase(
                            "tool_retry_think",
                            "done",
                            (
                                f"Loop {loops}: Think about retry for `{last_result.name}` "
                                f"(retryable={should_retry}, next_attempt={attempt_no + 1 if has_attempt_left else attempt_no}, mode={tool_mode})."
                            ),
                            {
                                "tool": last_result.name,
                                "loop": loops,
                                "attempt": attempt_no,
                                "max_attempts": max_attempts_for_call,
                                "mode": tool_mode,
                                "retryable": should_retry,
                                "has_budget": has_budget,
                                "has_attempt_left": has_attempt_left,
                            },
                        )
                        if should_retry and has_budget and has_attempt_left:
                            retry_attempts[key] = attempt_no
                            enqueue_call(call)
                            scheduled_retry = True
                            phase(
                                "tool_retry_scheduled",
                                "running",
                                (
                                    f"Loop {loops}: Schedule retry for `{last_result.name}` "
                                    f"(attempt {attempt_no + 1}/{max_attempts_for_call})."
                                ),
                                {
                                    "tool": last_result.name,
                                    "loop": loops,
                                    "attempt": attempt_no + 1,
                                    "max_attempts": max_attempts_for_call,
                                    "mode": tool_mode,
                                },
                            )

                    if not scheduled_retry:
                        executed_keys.add(key)
                        retry_attempts.pop(key, None)

                followups = self._infer_followup_calls(
                    user_message=user_message,
                    plan=plan,
                    tool_results=tool_results,
                    tool_states=tool_states,
                )
                for call in followups:
                    enqueue_call(call)
                    call_key = self._tool_call_key(call)
                    if all(self._tool_call_key(existing) != call_key for existing in plan.tool_calls):
                        plan.tool_calls.append(call)

                if followups:
                    phase(
                        "tool_followup",
                        "done",
                        f"Loop {loops}: discovered {len(followups)} follow-up tool candidate(s).",
                        {"round": loops, "count": len(followups), "tools": [c.name for c in followups]},
                    )

                phase(
                    "tool_round_complete",
                    "done",
                    (
                        f"Loop {loops}: cycle complete. "
                        f"Remaining queue={len(pending_calls)}, executed={len(executed_keys)}, acts={executed_actions}."
                    ),
                    {
                        "round": loops,
                        "remaining": len(pending_calls),
                        "executed": len(executed_keys),
                        "acts": executed_actions,
                    },
                )

            # Optional execution step (gated hard)
            exec_result = await self._maybe_execute_order(
                plan=plan,
                user_message=user_message,
                user_context=user_context,
                tool_states=tool_states,
            )
            if exec_result is not None:
                tool_results.append(exec_result)
                phase(
                    "execution_adapter",
                    "done" if exec_result.ok else "error",
                    "Execution adapter invoked.",
                    {"ok": exec_result.ok, "latency_ms": exec_result.latency_ms},
                )
                if not exec_result.ok:
                    plan.warnings.append(exec_result.error or "Execution call returned an error.")
            else:
                phase(
                    "execution_adapter",
                    "skipped",
                    "Execution adapter not triggered for this request.",
                )
        else:
            phase(
                "plan_blocked",
                "error",
                "Plan blocked by guardrails.",
                {"blocks": plan.blocks},
            )

        runtime_context = self._render_context(plan=plan, tool_results=tool_results)
        phase(
            "runtime_ready",
            "done",
            f"Runtime context ready with {len(tool_results)} tool results.",
            {"tool_results": len(tool_results), "memory_enabled": memory_enabled},
        )

        # Ensure core runtime phases are always present, even when skipped.
        ensure_phase("memory_think")
        ensure_phase("memory_act")
        ensure_phase("memory_observe")
        ensure_phase("knowledge_think")
        ensure_phase("knowledge_act")
        ensure_phase("knowledge_observe")
        ensure_phase("tool_round_start")
        ensure_phase("tool_execution")
        ensure_phase("tool_check")
        ensure_phase("tool_retry_think")
        ensure_phase("tool_retry_scheduled")
        ensure_phase("tool_followup")
        ensure_phase("tool_round_complete")
        ensure_phase("execution_adapter")
        ensure_phase("runtime_ready")

        return {
            "plan": plan,
            "tool_results": tool_results,
            "runtime_context": runtime_context,
            "phases": phases,
        }
