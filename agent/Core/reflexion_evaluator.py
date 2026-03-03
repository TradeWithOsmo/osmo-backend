"""
Reflexion Evaluator

Quality-assessment engine for the Reflexion Agent loop.

After every tool call the evaluator classifies the result as:
  GOOD    – data is complete and high-quality
  POOR    – result returned but data is incomplete / suspicious
  ERROR   – tool call failed with an error payload

When the result is POOR or ERROR the evaluator also produces a
human-readable ``suggested_fix`` string the agent uses to retry
with corrected arguments.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .reflexion_memory import ActionStatus

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

EvalResult = Tuple[ActionStatus, str, Optional[str]]
# (status, evaluation_note, suggested_fix_or_None)


# ---------------------------------------------------------------------------
# Tool category sets
# ---------------------------------------------------------------------------

_PRICE_TOOLS = {"get_price", "get_ticker_stats"}
_CANDLE_TOOLS = {"get_candles"}
_LEVEL_TOOLS = {"get_high_low_levels"}
_TA_TOOLS = {
    "get_technical_analysis",
    "get_technical_summary",
    "get_patterns",
    "get_indicators",
}
_INDICATOR_READ_TOOLS = {"get_active_indicators"}
_INDICATOR_WRITE_TOOLS = {"add_indicator", "remove_indicator", "clear_indicators"}
_DRAW_TOOLS = {"draw", "update_drawing", "clear_drawings"}
_SYMBOL_TOOLS = {"set_symbol"}
_TIMEFRAME_TOOLS = {"set_timeframe"}
_TRADE_SETUP_TOOLS = {"setup_trade", "add_price_alert", "mark_trading_session"}
_EXECUTION_TOOLS = {
    "place_order",
    "get_positions",
    "close_position",
    "close_all_positions",
    "reverse_position",
    "cancel_order",
    "adjust_position_tpsl",
    "adjust_all_positions_tpsl",
}
_RESEARCH_TOOLS = {"research_market", "compare_markets", "scan_market_overview"}
_WEB_TOOLS = {"search_news", "search_sentiment", "search_web_hybrid"}
_MEMORY_TOOLS = {"add_memory", "search_memory", "get_recent_history"}
_NAV_TOOLS = {
    "focus_chart",
    "ensure_mode",
    "pan",
    "zoom",
    "press_key",
    "reset_view",
    "focus_latest",
    "get_photo_chart",
    "hover_candle",
    "mouse_move",
    "mouse_press",
    "set_crosshair",
    "move_crosshair",
    "get_canvas",
    "get_box",
    "inspect_cursor",
    "capture_moment",
}
_DISCOVERY_TOOLS = {
    "list_supported_draw_tools",
    "list_supported_indicator_aliases",
    "verify_indicator_present",
}
_ORDERBOOK_TOOLS = {"get_orderbook", "get_funding_rate", "get_chainlink_price"}
_ANALYTICS_TOOLS = {"get_whale_activity", "get_token_distribution"}
_KNOWLEDGE_TOOLS = {"search_knowledge_base"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_error_payload(result: Any) -> Tuple[bool, str]:
    """Return (is_error, error_message) by inspecting common result shapes."""
    if not isinstance(result, dict):
        return False, ""
    err = result.get("error") or result.get("err") or ""
    if err:
        return True, str(err)
    if result.get("status") == "error":
        msg = result.get("message") or result.get("detail") or "status=error"
        return True, str(msg)
    if result.get("ok") is False:
        msg = result.get("error") or result.get("message") or "ok=False"
        return True, str(msg)
    return False, ""


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flatten_list(value: Any) -> List[Any]:
    """Extract a list from common result shapes."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "candles", "results", "items"):
            v = value.get(key)
            if isinstance(v, list):
                return v
    return []


# ---------------------------------------------------------------------------
# RWA / fiat detection
# ---------------------------------------------------------------------------

_FIAT_CODES = {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "MXN", "HKD"}
_RWA_BASES = {
    "XAU",
    "XAG",
    "XPD",
    "XPT",
    "CL",
    "HG",
    "AAPL",
    "TSLA",
    "MSFT",
    "GOOG",
    "AMZN",
    "META",
    "NVDA",
    "COIN",
    "PLTR",
    "DAX",
    "DJI",
    "FTSE",
    "NDX",
    "SPX",
    "NIK",
}


def _infer_asset_type(symbol: str) -> str:
    raw = str(symbol or "").upper().replace("/", "-").replace("_", "-")
    base = raw.split("-", 1)[0]
    if base in _RWA_BASES or base in _FIAT_CODES:
        return "rwa"
    return "crypto"


def _clean_symbol(symbol: str) -> str:
    """Strip common suffixes and return the base token."""
    raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if raw.endswith("USDT") and len(raw) > 4 and "-" not in raw:
        return raw[:-4]
    if raw.endswith("USD") and len(raw) > 3 and "-" not in raw:
        return raw[:-3]
    if "-" in raw:
        return raw.split("-", 1)[0]
    return raw


# ---------------------------------------------------------------------------
# Fix-suggestion engine
# ---------------------------------------------------------------------------


def _suggest_fix(
    tool_name: str,
    args: Dict[str, Any],
    error_msg: str,
) -> Optional[str]:
    """
    Map a known error pattern to a concrete repair instruction.
    The returned string will be shown to the LLM as a hint for retry.
    """
    lower = error_msg.lower()
    symbol = str(args.get("symbol") or args.get("target_symbol") or "").strip()
    asset_type = str(args.get("asset_type") or "").strip().lower()
    timeframe = str(args.get("timeframe") or "").strip()

    # Symbol not found on market
    if any(
        k in lower for k in ("not found", "symbol not found", "no data", "no market")
    ):
        clean = _clean_symbol(symbol)
        other_type = "rwa" if asset_type == "crypto" else "crypto"
        parts: List[str] = []
        if clean and clean.upper() != symbol.upper():
            parts.append(f"Try symbol='{clean}'")
        parts.append(f"Or switch asset_type='{other_type}'")
        return " | ".join(parts) if parts else f"Verify symbol='{symbol}' exists."

    # Not enough candle history
    if "not enough candle" in lower or "available=" in lower:
        lookback = _coerce_float(args.get("lookback"))
        if lookback and lookback > 3:
            new_lb = max(2, int(lookback) // 2)
            return f"Reduce lookback to {new_lb} (half of {int(lookback)})."
        return "Use a smaller lookback value, e.g. lookback=3."

    # Execution gated
    if "execution disabled" in lower:
        return (
            "Execution is off. Draw the trade proposal with setup_trade() "
            "so the human trader can review and approve it."
        )

    # Indicator name unknown
    if "indicator" in lower and ("not found" in lower or "unknown" in lower):
        return (
            "Call list_supported_indicator_aliases() to get the correct name, "
            "then retry add_indicator with the canonical indicator name."
        )

    # Wallet / user address missing
    if "user_address" in lower or "wallet" in lower or "missing user" in lower:
        return "Wallet not connected. Use setup_trade() to propose the trade instead."

    # Network / timeout
    if any(
        k in lower for k in ("timeout", "connection", "connect", "refused", "network")
    ):
        return f"Transient network error – retry {tool_name} with the same arguments."

    # HTTP 404 on candles
    if "404" in lower and tool_name in _CANDLE_TOOLS:
        tf_fallback = {"1D": "4H", "4H": "1H", "1H": "15m"}.get(timeframe.upper(), "1H")
        return f"Try timeframe='{tf_fallback}' or verify the symbol format."

    # Fiat/RWA TA not supported
    if "fiat-rwa" in lower or "unsupported" in lower:
        return (
            "Fiat/RWA pairs don't support technical_analysis. "
            "Use get_price() + search_news() for macro context instead."
        )

    # Invalid order side
    if "invalid side" in lower:
        return "Use side='buy' or side='sell'."

    # Max notional
    if "max_notional" in lower:
        m = re.search(r"\((\d+(?:\.\d+)?)\)", error_msg)
        cap = m.group(1) if m else "5000"
        return f"Reduce amount_usd to less than {cap}."

    # Drawing coordinate issue
    if tool_name == "draw" and (
        "points" in lower or "coordinates" in lower or "price" in lower
    ):
        return (
            "draw() needs valid price-level coordinates. "
            "First call get_high_low_levels() to obtain support/resistance prices, "
            "then use those values as the 'price' field in points."
        )

    return None


# ---------------------------------------------------------------------------
# Per-tool quality evaluators
# ---------------------------------------------------------------------------


def _eval_price(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    price = _coerce_float(result.get("price"))
    if price is None or price <= 0:
        sym = str(args.get("symbol", "unknown"))
        fix = _suggest_fix("get_price", args, f"Symbol '{sym}' not found in markets.")
        return ActionStatus.POOR, "Price is zero or missing", fix
    pct = result.get("change_percent_24h") or result.get("change_pct_24h")
    note = f"Price={price:.6g}"
    if pct is not None:
        note += f", 24h={pct:+.2f}%"
    return ActionStatus.GOOD, note, None


def _eval_candles(args: Dict[str, Any], result: Any) -> EvalResult:
    rows = _flatten_list(result)
    limit = int(args.get("limit") or 100)
    if len(rows) == 0:
        fix = "Verify symbol format and timeframe, or reduce limit."
        return ActionStatus.POOR, "Empty candles response", fix
    if len(rows) < max(3, limit // 10):
        return (
            ActionStatus.POOR,
            f"Too few candles: {len(rows)} (expected ~{limit})",
            "Try a more liquid timeframe (1H, 4H, 1D) or reduce limit.",
        )
    return ActionStatus.GOOD, f"Candles OK: {len(rows)} bars", None


def _eval_levels(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    support = _coerce_float(result.get("support"))
    resistance = _coerce_float(result.get("resistance"))
    if support is None or resistance is None:
        fix = _suggest_fix(
            "get_high_low_levels",
            args,
            result.get("error") or "Missing support/resistance",
        )
        return ActionStatus.POOR, "Support/resistance levels missing", fix
    if support >= resistance:
        return (
            ActionStatus.POOR,
            f"Invalid levels: support({support:.4f}) >= resistance({resistance:.4f})",
            "Increase lookback to widen the sampling window.",
        )
    spread_pct = ((resistance - support) / support * 100) if support > 0 else 0
    return (
        ActionStatus.GOOD,
        f"Levels OK – S={support:.4f} R={resistance:.4f} spread={spread_pct:.2f}%",
        None,
    )


def _eval_technical_analysis(
    args: Dict[str, Any], result: Dict[str, Any]
) -> EvalResult:
    indicators = result.get("indicators") or {}
    patterns = result.get("patterns") or []
    if not isinstance(indicators, dict) or len(indicators) == 0:
        fix = None
        err_text = str(result.get("error") or "")
        if "fiat" in err_text.lower() or "unsupported" in err_text.lower():
            fix = "Fiat/RWA pair: skip TA and use get_price() + search_news() instead."
        return ActionStatus.POOR, "No indicators in TA result", fix
    rsi = indicators.get("RSI_14") or indicators.get("RSI")
    note = f"TA OK: {len(indicators)} indicators"
    if rsi is not None:
        mood = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
        note += f", RSI={rsi:.1f}({mood})"
    if patterns:
        note += f", patterns={patterns[:3]}"
    return ActionStatus.GOOD, note, None


def _eval_active_indicators(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    info = str(result.get("info") or "")
    if "not found" in info.lower():
        return ActionStatus.GOOD, "Chart has no indicators yet (clean state)", None
    payload = result.get("data") or {}
    active = payload.get("active_indicators") if isinstance(payload, dict) else []
    count = len(active) if isinstance(active, list) else 0
    sample = active[:5] if isinstance(active, list) else []
    return ActionStatus.GOOD, f"Active indicators: {count} → {sample}", None


def _eval_add_indicator(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    name = str(args.get("name") or "")
    status_val = str(result.get("status") or "")
    err = result.get("error")
    if err or status_val == "error":
        fix = (
            "Call list_supported_indicator_aliases() for the correct name, "
            "then retry add_indicator."
        )
        return ActionStatus.POOR, f"add_indicator('{name}') uncertain: {err}", fix
    return ActionStatus.GOOD, f"Indicator '{name}' added to chart", None


def _eval_draw(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    tool_type = str(args.get("tool") or "shape")
    if result.get("error") or result.get("status") == "error":
        err = str(result.get("error") or "unknown")
        fix = _suggest_fix("draw", args, err)
        return ActionStatus.POOR, f"draw('{tool_type}') uncertain: {err}", fix
    return ActionStatus.GOOD, f"Drawing '{tool_type}' placed on chart", None


def _eval_set_symbol(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    target = str(args.get("target_symbol") or "")
    if result.get("error") or result.get("status") == "error":
        err = str(result.get("error") or "")
        fix = f"Verify '{target}' is listed on the target exchange."
        return ActionStatus.POOR, f"Symbol switch to '{target}' uncertain: {err}", fix
    return ActionStatus.GOOD, f"Chart switched to {target}", None


def _eval_set_timeframe(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    tf = str(args.get("timeframe") or "")
    if result.get("error"):
        return ActionStatus.POOR, f"Timeframe '{tf}' not confirmed", None
    return ActionStatus.GOOD, f"Timeframe set to {tf}", None


def _eval_setup_trade(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    if result.get("error") or result.get("status") == "error":
        err = str(result.get("error") or "")
        return ActionStatus.POOR, f"Trade setup failed: {err}", None
    side = str(args.get("side") or "")
    entry = _coerce_float(args.get("entry"))
    note = f"Trade setup drawn on chart: {side}"
    if entry is not None:
        note += f" @ {entry:.4f}"
    return ActionStatus.GOOD, note, None


def _eval_execution(
    tool_name: str, args: Dict[str, Any], result: Dict[str, Any]
) -> EvalResult:
    if result.get("status") == "proposal":
        return (
            ActionStatus.GOOD,
            f"{tool_name}: order proposal created (HITL mode)",
            None,
        )
    if result.get("ok") is True or (
        result.get("status") not in (None, "error") and not result.get("error")
    ):
        return ActionStatus.GOOD, f"{tool_name}: executed successfully", None
    # No explicit ok/status but also no error indicators — treat as success.
    # Covers tools like get_positions which return {"positions": [...], "account": {...}}
    # without an ok/status field. By this point _is_error_payload() has already
    # ruled out any dict that carries "error", "status=error", or "ok=False".
    if result.get("ok") is not False and not result.get("error"):
        return ActionStatus.GOOD, f"{tool_name}: completed", None
    err = str(result.get("error") or "")
    fix = _suggest_fix(tool_name, args, err)
    return ActionStatus.ERROR, f"{tool_name} failed: {err}", fix


def _eval_research(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    available = int(result.get("markets_available") or 0)
    if available == 0:
        sym = str(args.get("symbol") or "")
        fix = f"Try different symbol format for '{sym}' or use scan_market_overview()."
        return ActionStatus.POOR, "No markets available for symbol", fix
    spread = result.get("spread_pct")
    note = f"Research OK: {available} markets available"
    if spread is not None:
        note += f", cross-spread={spread:.4f}%"
    return ActionStatus.GOOD, note, None


def _eval_web_search(args: Dict[str, Any], result: Dict[str, Any]) -> EvalResult:
    status = str(result.get("status") or "")
    if status == "ok":
        return ActionStatus.GOOD, "Web search returned results", None
    if status == "partial":
        return ActionStatus.GOOD, "Partial web results (one source failed)", None
    return (
        ActionStatus.POOR,
        "Web search failed for both sources",
        "Retry search_news with a simpler, shorter query string.",
    )


def _eval_memory(
    tool_name: str, args: Dict[str, Any], result: Dict[str, Any]
) -> EvalResult:
    err = str(result.get("error") or "")
    if err and "failed" in err.lower():
        return (
            ActionStatus.POOR,
            f"Memory {tool_name} soft-failed: {err}",
            "Memory service may be unavailable – continue without it.",
        )
    if tool_name == "search_memory":
        count = int(result.get("count") or 0)
        return ActionStatus.GOOD, f"Memory search: {count} results", None
    return ActionStatus.GOOD, f"{tool_name} completed", None


def _eval_nav(tool_name: str, result: Dict[str, Any]) -> EvalResult:
    """Navigation tools are fire-and-forget; any non-fatal response is OK."""
    if result.get("error"):
        return ActionStatus.POOR, f"Nav {tool_name}: {result['error']}", None
    return ActionStatus.GOOD, f"Nav '{tool_name}' OK", None


def _eval_discovery(tool_name: str, result: Dict[str, Any]) -> EvalResult:
    if tool_name == "list_supported_draw_tools":
        count = int(result.get("count") or len(result.get("tools") or []))
        return ActionStatus.GOOD, f"Discovered {count} draw tools", None
    if tool_name == "list_supported_indicator_aliases":
        count = int(result.get("aliases_count") or len(result.get("aliases") or []))
        return ActionStatus.GOOD, f"Discovered {count} indicator aliases", None
    if tool_name == "verify_indicator_present":
        present = bool(result.get("present"))
        indicator = str(result.get("indicator") or "")
        if present:
            return (
                ActionStatus.GOOD,
                f"Indicator '{indicator}' confirmed on chart",
                None,
            )
        attempts = result.get("attempts", "?")
        return (
            ActionStatus.POOR,
            f"Indicator '{indicator}' NOT found after {attempts} poll(s)",
            "Try add_indicator again, then call verify_indicator_present after ~2s.",
        )
    return ActionStatus.GOOD, "Discovery OK", None


def _eval_orderbook(
    tool_name: str, args: Dict[str, Any], result: Dict[str, Any]
) -> EvalResult:
    if tool_name == "get_funding_rate":
        rate = result.get("rate") or result.get("funding_rate")
        if rate is not None:
            return ActionStatus.GOOD, f"Funding rate: {rate}", None
        return ActionStatus.POOR, "Funding rate not available", None
    bids = result.get("bids") or []
    asks = result.get("asks") or []
    if bids and asks:
        return ActionStatus.GOOD, f"Orderbook: {len(bids)} bids, {len(asks)} asks", None
    return (
        ActionStatus.POOR,
        "Empty orderbook",
        "Orderbook is only available for crypto on Hyperliquid.",
    )


def _eval_analytics(
    tool_name: str, args: Dict[str, Any], result: Dict[str, Any]
) -> EvalResult:
    if result.get("error"):
        return (
            ActionStatus.POOR,
            f"{tool_name}: {result['error']}",
            "Dune analytics may be disabled – skip and continue without on-chain data.",
        )
    return ActionStatus.GOOD, f"{tool_name} OK", None


# ---------------------------------------------------------------------------
# Main evaluator class
# ---------------------------------------------------------------------------


class ReflexionEvaluator:
    """
    Stateless quality-assessment engine for the Reflexion Agent.

    Usage::

        evaluator = ReflexionEvaluator()
        status, note, fix = evaluator.evaluate("get_price", {"symbol": "BTC"}, result)
        if evaluator.should_retry(status, "get_price", retry_count=0):
            fixed_args = evaluator.apply_fix_to_args("get_price", original_args, fix)
            ...
    """

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
    ) -> EvalResult:
        """
        Classify a tool call result.

        Returns
        -------
        Tuple[ActionStatus, str, Optional[str]]
            ``(status, human-readable note, optional fix hint)``
        """
        # Guard: None result
        if result is None:
            return (
                ActionStatus.ERROR,
                f"Tool '{tool_name}' returned None",
                f"Retry {tool_name} with the same or adjusted arguments.",
            )

        # Guard: explicit error payload
        is_err, err_msg = _is_error_payload(result)
        if is_err:
            fix = _suggest_fix(tool_name, args, err_msg)
            return ActionStatus.ERROR, f"[{tool_name}] {err_msg}", fix

        # Non-dict results
        if not isinstance(result, dict):
            if isinstance(result, (list, str)) and result:
                return ActionStatus.GOOD, f"{tool_name}: non-empty result", None
            return (
                ActionStatus.POOR,
                f"{tool_name}: empty or unexpected type ({type(result).__name__})",
                None,
            )

        # ---- Route to per-tool evaluator ----

        if tool_name in _PRICE_TOOLS:
            return _eval_price(args, result)

        if tool_name in _CANDLE_TOOLS:
            return _eval_candles(args, result)

        if tool_name in _LEVEL_TOOLS:
            return _eval_levels(args, result)

        if tool_name in _TA_TOOLS:
            return _eval_technical_analysis(args, result)

        if tool_name in _INDICATOR_READ_TOOLS:
            return _eval_active_indicators(args, result)

        if tool_name in _INDICATOR_WRITE_TOOLS:
            return _eval_add_indicator(args, result)

        if tool_name in {"draw", "update_drawing"}:
            return _eval_draw(args, result)

        if tool_name == "clear_drawings":
            return ActionStatus.GOOD, "Drawings cleared from chart", None

        if tool_name in _SYMBOL_TOOLS:
            return _eval_set_symbol(args, result)

        if tool_name in _TIMEFRAME_TOOLS:
            return _eval_set_timeframe(args, result)

        if tool_name in _TRADE_SETUP_TOOLS:
            return _eval_setup_trade(args, result)

        if tool_name in _EXECUTION_TOOLS:
            return _eval_execution(tool_name, args, result)

        if tool_name in _RESEARCH_TOOLS:
            return _eval_research(args, result)

        if tool_name in _WEB_TOOLS:
            return _eval_web_search(args, result)

        if tool_name in _MEMORY_TOOLS:
            return _eval_memory(tool_name, args, result)

        if tool_name in _NAV_TOOLS:
            return _eval_nav(tool_name, result)

        if tool_name in _DISCOVERY_TOOLS:
            return _eval_discovery(tool_name, result)

        if tool_name in _ORDERBOOK_TOOLS:
            return _eval_orderbook(tool_name, args, result)

        if tool_name in _ANALYTICS_TOOLS:
            return _eval_analytics(tool_name, args, result)

        if tool_name in _KNOWLEDGE_TOOLS:
            hits = result.get("results") or result.get("matches") or []
            count = len(hits) if isinstance(hits, list) else 0
            return ActionStatus.GOOD, f"Knowledge search: {count} hits", None

        # Default fallback – non-error dict is acceptable
        return ActionStatus.GOOD, f"{tool_name}: completed OK", None

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def evaluate_batch(
        self,
        calls: List[Tuple[str, Dict[str, Any], Any]],
    ) -> List[EvalResult]:
        """Evaluate a list of ``(tool_name, args, result)`` tuples."""
        return [self.evaluate(name, args, result) for name, args, result in calls]

    # ------------------------------------------------------------------
    # Retry heuristic
    # ------------------------------------------------------------------

    def should_retry(
        self,
        status: ActionStatus,
        tool_name: str,
        retry_count: int,
        max_retries: int = 2,
    ) -> bool:
        """
        Return True if the agent should attempt another call for this tool.

        Rules:
        - Only retry ERROR or POOR results.
        - Never exceed max_retries.
        - Never retry NAV tools (fire-and-forget semantics).
        - Never retry MEMORY tools (soft failure is acceptable).
        - Discovery tools are called once only.
        """
        if status == ActionStatus.GOOD:
            return False
        if retry_count >= max_retries:
            return False
        if tool_name in _NAV_TOOLS:
            return False
        if tool_name in _MEMORY_TOOLS:
            return False
        if tool_name in _DISCOVERY_TOOLS and retry_count > 0:
            return False
        return status in (ActionStatus.ERROR, ActionStatus.POOR)

    # ------------------------------------------------------------------
    # Fix application
    # ------------------------------------------------------------------

    def apply_fix_to_args(
        self,
        tool_name: str,
        original_args: Dict[str, Any],
        fix_hint: Optional[str],
    ) -> Dict[str, Any]:
        """
        Parse a fix hint string and patch ``original_args`` accordingly.
        Returns a **new** dict; the original is never mutated.
        """
        if not fix_hint:
            return dict(original_args)

        fixed = dict(original_args)
        hint_lo = fix_hint.lower()

        # asset_type override
        if "asset_type='rwa'" in hint_lo or "asset_type=rwa" in hint_lo:
            fixed["asset_type"] = "rwa"
        elif "asset_type='crypto'" in hint_lo or "asset_type=crypto" in hint_lo:
            fixed["asset_type"] = "crypto"

        # symbol override  – e.g.  "Try symbol='BTC'"
        m = re.search(r"symbol='([^']+)'", fix_hint, re.IGNORECASE)
        if m:
            fixed["symbol"] = m.group(1)

        # lookback reduction  – e.g.  "Reduce lookback to 5"
        m = re.search(r"lookback[=\s]+(\d+)", hint_lo)
        if m:
            try:
                fixed["lookback"] = int(m.group(1))
            except ValueError:
                pass

        # timeframe override  – e.g.  "Try timeframe='4H'"
        m = re.search(r"timeframe='([^']+)'", fix_hint, re.IGNORECASE)
        if not m:
            m = re.search(r"timeframe\s*[:=]\s*([0-9a-zA-Z]+)", fix_hint, re.IGNORECASE)
        if m:
            fixed["timeframe"] = m.group(1)

        if tool_name == "add_indicator":
            inputs = fixed.get("inputs")
            if not isinstance(inputs, dict):
                inputs = {}
            period_match = re.search(r"period\s*[:=]\s*(\d+)", hint_lo)
            length_match = re.search(r"length\s*[:=]\s*(\d+)", hint_lo)
            generic_match = re.search(r"(?:period|length)\s*[:=]\s*(\d+)", hint_lo)

            if period_match:
                try:
                    inputs["period"] = int(period_match.group(1))
                    inputs.setdefault("length", int(period_match.group(1)))
                except ValueError:
                    pass
            if length_match:
                try:
                    inputs["length"] = int(length_match.group(1))
                except ValueError:
                    pass
            if generic_match and not period_match and not length_match:
                try:
                    val = int(generic_match.group(1))
                    inputs["period"] = val
                    inputs["length"] = val
                except ValueError:
                    pass
            if inputs:
                fixed["inputs"] = inputs

        # limit reduction
        if "reduce limit" in hint_lo:
            current = fixed.get("limit", 100)
            try:
                fixed["limit"] = max(10, int(current) // 2)
            except (TypeError, ValueError):
                fixed["limit"] = 50

        return fixed


__all__ = [
    "EvalResult",
    "ReflexionEvaluator",
]
