from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..Guardrails.risk_gate import RiskGate
from .planner import build_plan
from .tool_registry import get_tool_registry
from .tool_modes import WRITE_TOOL_NAMES as SHARED_WRITE_TOOL_NAMES
from ..Schema.agent_runtime import AgentPlan
from ..Schema.agent_runtime import PlanContext, ToolCall
from ..Core.llm_factory import LLMFactory

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

WRITE_TOOL_NAMES: Set[str] = set(SHARED_WRITE_TOOL_NAMES)

SYMBOL_REQUIRED_TOOLS: Set[str] = {
    "get_price",
    "get_candles",
    "get_high_low_levels",
    "get_orderbook",
    "get_funding_rate",
    "get_ticker_stats",
    "get_chainlink_price",
    "get_technical_analysis",
    "get_patterns",
    "get_indicators",
    "get_technical_summary",
    "get_whale_activity",
    "get_token_distribution",
    "get_active_indicators",
    "search_sentiment",
    "set_symbol",
    "set_timeframe",
    "add_indicator",
    "focus_chart",
    "reset_view",
    "focus_latest",
    "hover_candle",
    "inspect_cursor",
    "capture_moment",
    "adjust_position_tpsl",
}

TIMEFRAME_REQUIRED_TOOLS: Set[str] = {
    "get_candles",
    "get_high_low_levels",
    "get_technical_analysis",
    "get_patterns",
    "get_indicators",
    "get_technical_summary",
    "get_active_indicators",
    "set_timeframe",
}

ASSET_TYPE_REQUIRED_TOOLS: Set[str] = {
    "get_price",
    "get_candles",
    "get_high_low_levels",
    "get_orderbook",
    "get_funding_rate",
    "get_ticker_stats",
    "get_technical_analysis",
    "get_patterns",
    "get_indicators",
    "get_technical_summary",
}


class ReasoningOrchestrator:
    """
    Reasoning phase:
    user message -> planner(ai/system) -> guardrails -> finalized plan.
    """

    def _extend_unique(self, target: List[str], values: List[str]) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)

    def _normalize_planner_source(self, tool_states: Optional[Dict[str, Any]]) -> str:
        tool_states = tool_states or {}
        raw = str(tool_states.get("planner_source") or "").strip().lower()
        if raw in {"ai", "llm"}:
            return "ai"
        if raw in {"system", "deterministic", "rule"}:
            return "system"
        return "system"

    def _normalize_planner_fallback(self, tool_states: Optional[Dict[str, Any]], planner_source: str) -> str:
        tool_states = tool_states or {}
        raw = str(tool_states.get("planner_fallback") or "").strip().lower()
        if raw in {"none", "off", "disable"}:
            return "none"
        if raw in {"system", "deterministic"}:
            return "system"
        if planner_source == "ai":
            # AI-first default: do not silently route back to deterministic planner.
            return "none"
        return "none"

    def _resolve_planner_model_id(self, tool_states: Optional[Dict[str, Any]]) -> str:
        tool_states = tool_states or {}
        explicit = (
            tool_states.get("planner_model_id")
            or tool_states.get("runtime_model_id")
            or os.getenv("AI_PLANNER_MODEL_ID")
            or "openai/gpt-4o-mini"
        )
        value = str(explicit).strip()
        return value or "openai/gpt-4o-mini"

    def _extract_json_object(self, raw: str) -> Optional[str]:
        text = str(raw or "").strip()
        if not text:
            return None

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            return fenced_match.group(1).strip()

        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        return text[first : last + 1].strip()

    def _response_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                        continue
                    maybe_content = item.get("content")
                    if maybe_content:
                        parts.append(str(maybe_content))
                        continue
                parts.append(str(item))
            return "\n".join(p for p in parts if p)
        return str(content or "")

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def _normalize_timeframe(self, value: Any, fallback: str = "1H") -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        if not text:
            return fallback
        norm = text.upper()
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
        return mapping.get(norm, text)

    def _safe_context(self, payload: Dict[str, Any], tool_states: Optional[Dict[str, Any]]) -> PlanContext:
        tool_states = tool_states or {}
        raw_context = payload.get("context")
        context = raw_context if isinstance(raw_context, dict) else {}

        tf_fallback = "1H"
        raw_tf = tool_states.get("timeframe")
        if isinstance(raw_tf, str) and raw_tf.strip():
            tf_fallback = raw_tf.strip()
        elif isinstance(raw_tf, list) and raw_tf:
            first = raw_tf[0]
            if isinstance(first, str) and first.strip():
                tf_fallback = first.strip()

        side = str(context.get("side") or "").strip().lower() or None
        if side not in {"long", "short", "buy", "sell", None}:
            side = None

        order_type = str(context.get("order_type") or "market").strip().lower()
        if order_type not in {"market", "limit", "stop_limit"}:
            order_type = "market"

        leverage = max(1, min(self._safe_int(context.get("leverage"), 1), 125))
        amount_usd = self._safe_float(context.get("amount_usd"))
        limit_price = self._safe_float(context.get("limit_price"))
        stop_price = self._safe_float(context.get("stop_price"))
        tp = self._safe_float(context.get("tp") if context.get("tp") is not None else context.get("take_profit"))
        sl = self._safe_float(context.get("sl") if context.get("sl") is not None else context.get("stop_loss"))

        symbol = context.get("symbol")
        symbol_text = str(symbol).strip() if symbol is not None else None
        if symbol_text == "":
            symbol_text = None

        return PlanContext(
            symbol=symbol_text,
            timeframe=self._normalize_timeframe(context.get("timeframe"), fallback=tf_fallback),
            requested_execution=bool(context.get("requested_execution")),
            requested_news=bool(context.get("requested_news")),
            requested_sentiment=bool(context.get("requested_sentiment")),
            requested_whales=bool(context.get("requested_whales")),
            side=side,
            order_type=order_type,
            amount_usd=amount_usd,
            leverage=leverage,
            limit_price=limit_price,
            stop_price=stop_price,
            tp=tp,
            sl=sl,
        )

    def _safe_tool_calls(self, payload: Dict[str, Any]) -> tuple[List[ToolCall], List[str]]:
        raw_calls = payload.get("tool_calls")
        if not isinstance(raw_calls, list):
            return [], []

        allowed_tools = set(get_tool_registry().keys())
        output: List[ToolCall] = []
        warnings: List[str] = []
        for item in raw_calls[:10]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if "." in name and name.split(".")[-1] in allowed_tools:
                name = name.split(".")[-1]
            if name not in allowed_tools:
                warnings.append(f"AI planner proposed unknown tool `{name}`; skipped.")
                continue
            args = item.get("args")
            if not isinstance(args, dict):
                args = {}
            reason = str(item.get("reason") or "").strip()
            output.append(ToolCall(name=name, args=args, reason=reason))
        return output, warnings

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

    def _tool_call_key(self, call: ToolCall) -> Tuple[str, str]:
        return call.name, json.dumps(call.args, ensure_ascii=False, sort_keys=True, default=str)

    def _repair_ai_plan(
        self,
        plan: AgentPlan,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        tool_states: Optional[Dict[str, Any]],
    ) -> AgentPlan:
        tool_states = tool_states or {}
        shadow = build_plan(user_message=user_message, history=history, tool_states=tool_states)

        if not plan.context.symbol and shadow.context.symbol:
            plan.context.symbol = shadow.context.symbol
            self._extend_unique(plan.warnings, ["AI planner omitted symbol; symbol inferred from request context."])

        if (
            (not plan.context.timeframe or str(plan.context.timeframe).strip() == "")
            and shadow.context.timeframe
        ):
            plan.context.timeframe = shadow.context.timeframe
            self._extend_unique(plan.warnings, ["AI planner omitted timeframe; timeframe inferred from request context."])

        if plan.context.requested_execution:
            if not plan.context.side and shadow.context.side:
                plan.context.side = shadow.context.side
            if plan.context.amount_usd is None and shadow.context.amount_usd is not None:
                plan.context.amount_usd = shadow.context.amount_usd
            if (plan.context.leverage or 1) <= 1 and (shadow.context.leverage or 1) > 1:
                plan.context.leverage = shadow.context.leverage
            if plan.context.tp is None and shadow.context.tp is not None:
                plan.context.tp = shadow.context.tp
            if plan.context.sl is None and shadow.context.sl is not None:
                plan.context.sl = shadow.context.sl

        symbol = self._normalize_symbol(plan.context.symbol) or plan.context.symbol
        if symbol:
            plan.context.symbol = symbol
        timeframe = self._normalize_timeframe(plan.context.timeframe, fallback="1H")
        plan.context.timeframe = timeframe
        asset_type = self._infer_asset_type_from_symbol(symbol)
        tool_symbol = self._symbol_to_tool_symbol(symbol, asset_type) or symbol

        write_enabled = bool(tool_states.get("write"))
        dropped_write = 0
        repaired_calls: List[ToolCall] = []
        for call in plan.tool_calls:
            name = str(call.name or "").strip()
            if not name:
                continue

            if name in WRITE_TOOL_NAMES and not write_enabled:
                dropped_write += 1
                continue

            args: Dict[str, Any] = dict(call.args or {})

            if name in SYMBOL_REQUIRED_TOOLS and symbol:
                if name == "set_symbol":
                    args.setdefault("symbol", tool_states.get("market_symbol") or symbol)
                    args.setdefault("target_symbol", symbol)
                elif "symbol" not in args:
                    args["symbol"] = tool_symbol if name in {"get_price", "get_candles", "get_orderbook", "get_funding_rate", "get_ticker_stats", "get_chainlink_price", "get_whale_activity", "get_token_distribution", "search_sentiment"} else symbol

            if name in TIMEFRAME_REQUIRED_TOOLS and timeframe:
                args.setdefault("timeframe", timeframe)

            if name in ASSET_TYPE_REQUIRED_TOOLS and symbol:
                args.setdefault("asset_type", asset_type)

            repaired_calls.append(
                ToolCall(
                    name=name,
                    args=args,
                    reason=call.reason,
                )
            )

        if dropped_write > 0:
            self._extend_unique(
                plan.warnings,
                [f"Dropped {dropped_write} write tool(s) from AI plan because write mode is disabled."],
            )

        if not repaired_calls and plan.intent in {"analysis", "execution"} and symbol:
            repaired_calls = [
                ToolCall(
                    name="get_price",
                    args={"symbol": tool_symbol, "asset_type": asset_type},
                    reason="Bootstrap after AI plan repair: fetch live reference price.",
                ),
                ToolCall(
                    name="get_technical_analysis",
                    args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                    reason="Bootstrap after AI plan repair: fetch technical context.",
                ),
            ]
            self._extend_unique(
                plan.warnings,
                ["AI plan had no actionable tools; bootstrap analysis tools were added."],
            )

        seen: Set[Tuple[str, str]] = set()
        deduped: List[ToolCall] = []
        for call in repaired_calls:
            key = self._tool_call_key(call)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(call)

        if len(deduped) > 6:
            self._extend_unique(
                plan.warnings,
                [f"AI planner returned {len(deduped)} tools; trimmed to 6 for runtime budget."],
            )
        plan.tool_calls = deduped[:6]
        return plan

    def _safe_string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out[:8]

    def _build_minimal_ai_plan(self, tool_states: Optional[Dict[str, Any]]) -> AgentPlan:
        tool_states = tool_states or {}
        fallback_timeframe = "1H"
        raw_tf = tool_states.get("timeframe")
        if isinstance(raw_tf, str) and raw_tf.strip():
            fallback_timeframe = raw_tf.strip()
        elif isinstance(raw_tf, list) and raw_tf:
            first_tf = raw_tf[0]
            if isinstance(first_tf, str) and first_tf.strip():
                fallback_timeframe = first_tf.strip()
        return AgentPlan(intent="analysis", context=PlanContext(timeframe=fallback_timeframe))

    def _build_plan_with_ai(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]],
        tool_states: Optional[Dict[str, Any]],
    ) -> AgentPlan:
        tool_states = tool_states or {}
        model_id = self._resolve_planner_model_id(tool_states)
        reasoning_effort = tool_states.get("planner_reasoning_effort") or tool_states.get("reasoning_effort")
        llm = LLMFactory.get_llm(model_id=model_id, temperature=0.1, reasoning_effort=reasoning_effort)

        available_tools = sorted(get_tool_registry().keys())
        tool_names = ", ".join(available_tools)

        system_prompt = (
            "You are an AI planner for a trading agent. "
            "Your only task is to output a single JSON object (no markdown, no extra text). "
            "Do not call tools. Do not include explanations outside JSON.\n"
            "JSON schema:\n"
            "{\n"
            '  "intent": "analysis|execution|education|smalltalk|other",\n'
            '  "context": {\n'
            '    "symbol": "optional string like BTC-USD",\n'
            '    "timeframe": "optional timeframe like 1H",\n'
            '    "requested_execution": false,\n'
            '    "requested_news": false,\n'
            '    "requested_sentiment": false,\n'
            '    "requested_whales": false,\n'
            '    "side": "optional long|short|buy|sell",\n'
            '    "order_type": "optional market|limit|stop_limit",\n'
            '    "amount_usd": null,\n'
            '    "leverage": 1,\n'
            '    "limit_price": null,\n'
            '    "stop_price": null,\n'
            '    "tp": null,\n'
            '    "sl": null\n'
            "  },\n"
            '  "tool_calls": [\n'
            '    {"name": "tool_name", "args": {}, "reason": "why"}\n'
            "  ],\n"
            '  "warnings": ["optional warning"],\n'
            '  "blocks": ["optional guardrail pre-warning"]\n'
            "}\n"
            f"Allowed tool names: {tool_names}\n"
            "Rules:\n"
            "- Prefer minimal tool calls needed for high-quality analysis.\n"
            "- If user asks analysis, include read tools only.\n"
            "- Write tools are allowed only if explicit chart mutation intent.\n"
            "- Keep tool_calls <= 6.\n"
        )

        history_block = ""
        if isinstance(history, list) and history:
            compact_history: List[Dict[str, str]] = []
            for item in history[-6:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                if role not in {"system", "user", "assistant"}:
                    continue
                content = str(item.get("content") or "")
                compact_history.append({"role": role, "content": content[:500]})
            if compact_history:
                history_block = json.dumps(compact_history, ensure_ascii=False)

        user_prompt = (
            f"user_message: {user_message}\n"
            f"tool_states: {json.dumps(tool_states, ensure_ascii=False, default=str)}\n"
            f"history: {history_block or '[]'}\n"
            "Output JSON now."
        )

        response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        raw_content = self._response_content_to_text(getattr(response, "content", ""))
        parsed_json = self._extract_json_object(raw_content)
        if not parsed_json:
            raise ValueError("AI planner returned no JSON object.")

        payload = json.loads(parsed_json)
        if not isinstance(payload, dict):
            raise ValueError("AI planner JSON root is not an object.")

        intent = str(payload.get("intent") or "analysis").strip().lower() or "analysis"
        context = self._safe_context(payload, tool_states=tool_states)
        tool_calls, tool_warnings = self._safe_tool_calls(payload)
        warnings = self._safe_string_list(payload.get("warnings"))
        warnings.extend(tool_warnings)
        blocks = self._safe_string_list(payload.get("blocks"))

        plan = AgentPlan(
            intent=intent,
            context=context,
            tool_calls=tool_calls[:6],
            warnings=warnings,
            blocks=blocks,
        )
        return self._repair_ai_plan(
            plan=plan,
            user_message=user_message,
            history=history,
            tool_states=tool_states,
        )

    def build_plan(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        tool_states: Optional[Dict[str, Any]] = None,
    ) -> AgentPlan:
        planner_source = self._normalize_planner_source(tool_states)
        planner_fallback = self._normalize_planner_fallback(tool_states, planner_source=planner_source)

        plan: AgentPlan
        if planner_source == "ai":
            try:
                plan = self._build_plan_with_ai(
                    user_message=user_message,
                    history=history,
                    tool_states=tool_states,
                )
            except Exception as ai_error:
                if planner_fallback == "system":
                    plan = build_plan(user_message=user_message, history=history, tool_states=tool_states)
                    self._extend_unique(
                        plan.warnings,
                        [f"AI planner failed; fallback to system planner. error={ai_error}"],
                    )
                else:
                    plan = self._build_minimal_ai_plan(tool_states=tool_states)
                    self._extend_unique(
                        plan.warnings,
                        [f"AI planner failed and fallback disabled: {ai_error}"],
                    )
        else:
            plan = build_plan(user_message=user_message, history=history, tool_states=tool_states)

        risk_state = dict(tool_states or {})
        risk_state["requested_amount_usd"] = plan.context.amount_usd
        risk_state["requested_leverage"] = plan.context.leverage
        guardrail = RiskGate.evaluate(user_message, tool_states=risk_state)
        self._extend_unique(plan.warnings, guardrail.get("warnings", []))
        self._extend_unique(plan.blocks, guardrail.get("blocks", []))
        return plan
