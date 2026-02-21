"""
Reasoning Orchestrator

Lightweight planner used by websocket `/api/agent/plan/preview`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

_TIMEFRAME_RE = re.compile(r"\b(1m|3m|5m|15m|30m|1h|4h|1d|1w|60|240|d|w)\b", re.I)
_SYMBOL_RE = re.compile(
    r"\b([A-Z]{2,8}(?:[-/](?:USD|USDT|EUR|GBP|JPY|CHF|AUD|NZD|USDC))?)\b"
)


@dataclass(slots=True)
class PlanContext:
    symbol: str = ""
    timeframe: str = ""


@dataclass(slots=True)
class ToolCall:
    name: str
    reason: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReasoningPlan:
    intent: str = "analysis"
    context: PlanContext = field(default_factory=PlanContext)
    tool_calls: List[ToolCall] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_symbol(raw: str) -> str:
    value = _as_str(raw).upper().replace("_", "-").replace("/", "-")
    if not value:
        return ""
    if value.endswith("USDT") and len(value) > 4 and "-" not in value:
        return f"{value[:-4]}-USD"
    if value.endswith("USD") and len(value) > 3 and "-" not in value:
        return f"{value[:-3]}-USD"
    return value


def _normalize_timeframe(raw: str) -> str:
    value = _as_str(raw).upper().replace(" ", "")
    mapping = {
        "60": "1H",
        "240": "4H",
        "D": "1D",
        "W": "1W",
        "1M": "1m",
        "3M": "3m",
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
    }
    return mapping.get(value, value)


def _pick_context(
    user_message: str,
    history: Optional[List[Dict[str, Any]]],
    tool_states: Dict[str, Any],
) -> PlanContext:
    symbol = _normalize_symbol(
        tool_states.get("market_symbol")
        or tool_states.get("market")
        or tool_states.get("market_display")
        or tool_states.get("symbol")
    )
    timeframe = _normalize_timeframe(
        tool_states.get("market_timeframe")
        or (
            (tool_states.get("timeframe") or [None])[0]
            if isinstance(tool_states.get("timeframe"), list)
            else tool_states.get("timeframe")
        )
        or tool_states.get("preferred_timeframe")
    )

    if not symbol:
        probe = _as_str(user_message).upper().replace("/", "-").replace("_", "-")
        match = _SYMBOL_RE.search(probe)
        if not match and history:
            for item in reversed(history[-4:]):
                match = _SYMBOL_RE.search(
                    _as_str(item.get("content", "")).upper().replace("/", "-")
                )
                if match:
                    break
        symbol = _normalize_symbol(match.group(1) if match else "")

    if not timeframe:
        tf_match = _TIMEFRAME_RE.search(_as_str(user_message))
        timeframe = _normalize_timeframe(tf_match.group(1) if tf_match else "")

    return PlanContext(symbol=symbol, timeframe=timeframe)


def _detect_intent(message: str) -> str:
    text = _as_str(message).lower()
    if any(
        key in text
        for key in (
            "place order",
            "entry",
            "execute",
            "buy",
            "sell",
            "tp",
            "sl",
            "long",
            "short",
        )
    ):
        return "execution"
    if any(key in text for key in ("news", "sentiment", "headline", "research")):
        return "research"
    return "analysis"


def _bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = _as_str(value).lower()
    return raw in {"1", "true", "yes", "on"}


class ReasoningOrchestrator:
    """Planner for lightweight tool-call previews."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def build_plan(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> ReasoningPlan:
        safe_states = dict(tool_states or {})
        context = _pick_context(
            user_message=user_message,
            history=history,
            tool_states=safe_states,
        )
        intent = _detect_intent(user_message)
        plan = ReasoningPlan(intent=intent, context=context)

        max_actions_raw = safe_states.get("max_tool_actions", 4)
        try:
            max_actions = max(1, min(int(max_actions_raw), 8))
        except Exception:
            max_actions = 4

        if not context.symbol:
            plan.warnings.append(
                "No active market symbol detected; data tools may need explicit symbol."
            )

        tf = context.timeframe or "1H"
        symbol = context.symbol or "BTC-USD"
        asset_type = (
            "rwa"
            if "-" in symbol
            and symbol.split("-", 1)[0]
            in {
                "USD",
                "EUR",
                "GBP",
                "CHF",
                "JPY",
                "CAD",
                "AUD",
                "NZD",
            }
            else "crypto"
        )

        if intent in {"analysis", "execution"}:
            plan.tool_calls.extend(
                [
                    ToolCall(
                        name="get_price",
                        reason="Fetch latest price context before decision",
                        args={"symbol": symbol, "asset_type": asset_type},
                    ),
                    ToolCall(
                        name="get_candles",
                        reason="Gather OHLC context for timeframe analysis",
                        args={
                            "symbol": symbol,
                            "timeframe": tf,
                            "limit": 120,
                            "asset_type": asset_type,
                        },
                    ),
                    ToolCall(
                        name="get_technical_analysis",
                        reason="Generate compact technical summary",
                        args={
                            "symbol": symbol,
                            "timeframe": tf,
                            "asset_type": asset_type,
                        },
                    ),
                ]
            )

        if intent == "research":
            plan.tool_calls.extend(
                [
                    ToolCall(
                        name="search_news",
                        reason="Collect recent news for the requested topic",
                        args={
                            "query": user_message,
                            "mode": "quality",
                            "source": "news",
                        },
                    ),
                    ToolCall(
                        name="search_sentiment",
                        reason="Estimate sentiment bias for the active market",
                        args={"symbol": symbol},
                    ),
                ]
            )

        execution_enabled = _bool_flag(safe_states.get("execution"))
        if intent == "execution" and not execution_enabled:
            plan.blocks.append(
                "Execution disabled by runtime policy (execution=false)."
            )

        plan.tool_calls = plan.tool_calls[:max_actions]
        return plan

    async def process(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = self.build_plan(
            user_message=user_message,
            history=history,
            tool_states=tool_states,
        )
        return {
            "response": "plan_ready",
            "reasoning_steps": [],
            "plan": asdict(plan),
        }


__all__ = ["ReasoningOrchestrator", "ReasoningPlan", "PlanContext", "ToolCall"]
