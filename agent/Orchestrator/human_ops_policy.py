from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ..Schema.agent_runtime import AgentPlan, ToolCall, ToolResult
from .tool_modes import CHART_WRITE_TOOL_NAMES

RELIABILITY_MODES: Set[str] = {"strict", "balanced", "aggressive"}
RECOVERY_MODES: Set[str] = {"fail_fast", "recover_then_continue", "best_effort"}

NON_RECOVERABLE_FAILURE_MARKERS: Set[str] = {
    "unknown tool",
    "requires write mode",
    "allow write",
    "missing required",
    "validation error",
    "invalid argument",
    "blocked by",
    "not supported",
    "unsupported",
}

RECOVERY_CANDIDATE_WRITE_TOOLS: Set[str] = {
    "set_symbol",
    "set_timeframe",
    "add_indicator",
    "remove_indicator",
    "clear_indicators",
    "draw",
    "update_drawing",
    "clear_drawings",
    "setup_trade",
    "add_price_alert",
    "mark_trading_session",
}


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


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    if not raw:
        return ""
    if "-" in raw:
        base, quote = raw.split("-", 1)
        if quote in {"USD", "USDT"}:
            return f"{base}-USD"
        return f"{base}-{quote}"
    if raw.endswith("USDT") and len(raw) > 4:
        return f"{raw[:-4]}-USD"
    if raw.endswith("USD") and len(raw) > 3:
        return f"{raw[:-3]}-USD"
    if raw.isalpha() and 2 <= len(raw) <= 12:
        return f"{raw}-USD"
    return raw


def normalize_reliability_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    if mode in RELIABILITY_MODES:
        return mode
    return "balanced"


def normalize_recovery_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    if mode in RECOVERY_MODES:
        return mode
    return "recover_then_continue"


def default_max_tool_actions_for_mode(mode: str) -> int:
    normalized = normalize_reliability_mode(mode)
    if normalized == "strict":
        return 6
    if normalized == "aggressive":
        return 10
    return 8


def default_recovery_attempt_cap_for_mode(mode: str) -> int:
    normalized = normalize_reliability_mode(mode)
    if normalized == "aggressive":
        return 2
    return 1


def default_tool_retry_attempts_for_mode(mode: str) -> int:
    normalized = normalize_reliability_mode(mode)
    if normalized == "strict":
        return 1
    if normalized == "aggressive":
        return 3
    return 2


def recovery_attempt_cap(tool_states: Optional[Dict[str, Any]], reliability_mode: str) -> int:
    states = tool_states or {}
    raw = states.get("recovery_attempt_cap")
    try:
        parsed = int(raw) if raw is not None else default_recovery_attempt_cap_for_mode(reliability_mode)
    except Exception:
        parsed = default_recovery_attempt_cap_for_mode(reliability_mode)
    return max(1, min(parsed, 3))


def should_attempt_recovery(
    *,
    call: ToolCall,
    tool_mode: str,
    result: ToolResult,
    recovery_mode: str,
) -> bool:
    if normalize_recovery_mode(recovery_mode) != "recover_then_continue":
        return False
    if tool_mode != "write":
        return False
    if call.name not in RECOVERY_CANDIDATE_WRITE_TOOLS:
        return False
    text = str(result.error or "").strip().lower()
    if not text:
        return True
    return not any(marker in text for marker in NON_RECOVERABLE_FAILURE_MARKERS)


def _active_symbol_from_state(tool_states: Optional[Dict[str, Any]]) -> str:
    states = tool_states or {}
    return _normalize_symbol(
        states.get("market_symbol") or states.get("market") or states.get("market_display")
    )


def _target_symbol_from_call_or_plan(call: ToolCall, plan: AgentPlan) -> str:
    args = call.args or {}
    symbol = (
        args.get("target_symbol")
        or args.get("symbol")
        or getattr(plan.context, "symbol", None)
    )
    return _normalize_symbol(symbol)


def _target_timeframe_from_call_or_plan(call: ToolCall, plan: AgentPlan) -> str:
    args = call.args or {}
    # Timeframe SoT for recovery must come from explicit tool args only.
    timeframe = str(args.get("timeframe") or "").strip()
    return timeframe


def build_recovery_calls(
    *,
    failed_call: ToolCall,
    plan: AgentPlan,
    tool_states: Optional[Dict[str, Any]],
    result: ToolResult,
) -> List[ToolCall]:
    write_enabled = _parse_bool((tool_states or {}).get("write"), default=False)
    if not write_enabled:
        return []

    reason = str(result.error or "").strip().lower()
    failed_name = str(failed_call.name or "").strip()
    active_symbol = _active_symbol_from_state(tool_states)
    target_symbol = _target_symbol_from_call_or_plan(failed_call, plan)
    timeframe = _target_timeframe_from_call_or_plan(failed_call, plan)

    calls: List[ToolCall] = []
    needs_symbol_sync = (
        bool(target_symbol)
        and bool(active_symbol)
        and active_symbol != target_symbol
        and failed_name != "set_symbol"
        and (
            "mismatch=symbol" in reason
            or "symbol" in reason
            or failed_call.name in {"set_symbol", "add_indicator", "remove_indicator", "draw", "setup_trade"}
        )
    )
    needs_timeframe_sync = (
        bool(target_symbol)
        and bool(timeframe)
        and failed_name != "set_timeframe"
        and (
            "mismatch=timeframe" in reason
            or "timeframe" in reason
            or failed_call.name in {"set_timeframe", "add_indicator", "remove_indicator"}
        )
    )

    if needs_symbol_sync:
        calls.append(
            ToolCall(
                name="set_symbol",
                args={"symbol": active_symbol, "target_symbol": target_symbol},
                reason="Recovery: re-sync chart symbol before retrying failed write action.",
            )
        )
    if needs_timeframe_sync:
        calls.append(
            ToolCall(
                name="set_timeframe",
                args={"symbol": target_symbol, "timeframe": timeframe},
                reason="Recovery: re-sync timeframe before retrying failed write action.",
            )
        )

    should_verify = bool(target_symbol) and (
        bool(calls)
        or failed_name in RECOVERY_CANDIDATE_WRITE_TOOLS
    )
    if should_verify:
        verify_args: Dict[str, Any] = {"symbol": target_symbol}
        if timeframe:
            verify_args["timeframe"] = timeframe
        calls.append(
            ToolCall(
                name="verify_tradingview_state",
                args=verify_args,
                reason="Recovery: verify chart state after re-sync.",
            )
        )

    deduped: List[ToolCall] = []
    seen: Set[str] = set()
    for call in calls:
        key = f"{call.name}|{sorted((call.args or {}).items())}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)
    return deduped


def requires_strict_write_verify(call: ToolCall) -> bool:
    return call.name in CHART_WRITE_TOOL_NAMES


def _call_symbol(call: ToolCall, plan: AgentPlan, tool_states: Optional[Dict[str, Any]]) -> str:
    args = call.args or {}
    value = (
        args.get("target_symbol")
        or args.get("symbol")
        or getattr(plan.context, "symbol", None)
        or (tool_states or {}).get("market_symbol")
        or (tool_states or {}).get("market")
        or (tool_states or {}).get("market_display")
    )
    return _normalize_symbol(value)


def _call_timeframe(call: ToolCall, plan: AgentPlan) -> str:
    args = call.args or {}
    # Guard verifiers should not inherit UI chip/default timeframe from plan context.
    return str(args.get("timeframe") or "").strip()


def inject_human_ops_guards(
    *,
    plan: AgentPlan,
    tool_states: Optional[Dict[str, Any]],
    available_tools: Optional[Set[str]] = None,
) -> int:
    """
    Inject human-like guard calls into plan flow:
    - verify chart state after chart write actions
    - verify indicator presence before indicator reads when add_indicator happened earlier
    """
    if not isinstance(plan, AgentPlan) or not isinstance(plan.tool_calls, list):
        return 0
    if not _parse_bool((tool_states or {}).get("write"), default=False):
        return 0
    available = set(available_tools or set())

    original = list(plan.tool_calls)
    out: List[ToolCall] = []
    inserted = 0
    last_added_indicator_name: Optional[str] = None

    for idx, call in enumerate(original):
        out.append(call)
        call_name = str(call.name or "").strip()
        call_args = call.args or {}

        if call_name == "add_indicator":
            indicator_name = str(call_args.get("name") or "").strip()
            if indicator_name:
                last_added_indicator_name = indicator_name

        if call_name in {"get_indicators", "get_active_indicators"} and last_added_indicator_name:
            if available and "verify_indicator_present" not in available:
                continue
            prev_name = out[-2].name if len(out) >= 2 else ""
            if prev_name != "verify_indicator_present":
                verify_indicator_args: Dict[str, Any] = {
                    "symbol": _call_symbol(call, plan, tool_states),
                    "name": last_added_indicator_name,
                }
                timeframe = _call_timeframe(call, plan)
                if timeframe:
                    verify_indicator_args["timeframe"] = timeframe
                verify_indicator = ToolCall(
                    name="verify_indicator_present",
                    args=verify_indicator_args,
                    reason="Human-ops guard: verify indicator exists before reading indicator values.",
                )
                out.insert(len(out) - 1, verify_indicator)
                inserted += 1

        if call_name in CHART_WRITE_TOOL_NAMES:
            if available and "verify_tradingview_state" not in available:
                continue
            next_call_name = str(original[idx + 1].name or "").strip() if idx + 1 < len(original) else ""
            if next_call_name == "verify_tradingview_state":
                continue

            verify_args: Dict[str, Any] = {"symbol": _call_symbol(call, plan, tool_states)}
            timeframe = _call_timeframe(call, plan)
            if timeframe:
                verify_args["timeframe"] = timeframe
            if call_name == "add_indicator":
                indicator_name = str(call_args.get("name") or "").strip()
                if indicator_name:
                    verify_args["require_indicators"] = [indicator_name]
            if call_name == "remove_indicator":
                indicator_name = str(call_args.get("name") or "").strip()
                if indicator_name:
                    verify_args["forbid_indicators"] = [indicator_name]

            out.append(
                ToolCall(
                    name="verify_tradingview_state",
                    args=verify_args,
                    reason="Human-ops guard: verify chart state after write action.",
                )
            )
            inserted += 1

    if inserted > 0:
        plan.tool_calls = out
    return inserted
