from __future__ import annotations

from typing import Any, Dict, Set


TOOL_NAME_ALIASES: Dict[str, str] = {
    "price": "get_price",
    "candles": "get_candles",
    "technical_analysis": "get_technical_analysis",
    "active_indicators": "get_active_indicators",
    "clear_drawing": "clear_drawings",
    "set_pair": "set_symbol",
    "switch_symbol": "set_symbol",
}


def canonicalize_tool_name(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    key = raw.lower().replace("-", "_").replace(" ", "_")
    return TOOL_NAME_ALIASES.get(key, raw)


def adapt_tool_arguments(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    param_names: Set[str],
    tool_states: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    kwargs = dict(arguments or {})
    states = dict(tool_states or {})

    if tool_name == "search_sentiment":
        if not kwargs.get("symbol") and kwargs.get("query"):
            kwargs["symbol"] = kwargs.pop("query")
    if tool_name == "search_news":
        if not kwargs.get("query") and kwargs.get("symbol"):
            kwargs["query"] = kwargs.pop("symbol")

    if tool_name == "set_symbol":
        if not kwargs.get("target_symbol"):
            alias_target = (
                kwargs.get("new_symbol")
                or kwargs.get("to_symbol")
                or kwargs.get("asset")
            )
            if alias_target:
                kwargs["target_symbol"] = alias_target
        if not kwargs.get("target_symbol") and kwargs.get("symbol"):
            target_symbol = str(kwargs.get("symbol") or "").strip()
            if target_symbol:
                current_symbol = str(states.get("market_symbol") or "").strip()
                kwargs["target_symbol"] = target_symbol
                kwargs["symbol"] = current_symbol or target_symbol

    if tool_name == "setup_trade":
        if kwargs.get("entry") is None and kwargs.get("entry_price") is not None:
            kwargs["entry"] = kwargs.pop("entry_price")
        if kwargs.get("sl") is None:
            for alias in ("stop_loss", "stoploss", "stop", "sl_price"):
                if kwargs.get(alias) is not None:
                    kwargs["sl"] = kwargs.get(alias)
                    break
        if kwargs.get("tp") is None:
            for alias in ("take_profit", "tp_price", "target"):
                if kwargs.get(alias) is not None:
                    kwargs["tp"] = kwargs.get(alias)
                    break
        if kwargs.get("validation") is None and kwargs.get("gp") is not None:
            kwargs["validation"] = kwargs.get("gp")
        if kwargs.get("invalidation") is None and kwargs.get("gl") is not None:
            kwargs["invalidation"] = kwargs.get("gl")

    if tool_name in {"set_timeframe", "setup_trade"}:
        active_symbol = str(states.get("market_symbol") or "").strip()
        requested_symbol = str(kwargs.get("symbol") or "").strip()
        if active_symbol and requested_symbol and active_symbol != requested_symbol:
            kwargs["symbol"] = active_symbol

    if tool_name == "mark_trading_session" and kwargs.get("session") is not None:
        raw_session = str(kwargs.get("session") or "").strip().upper()
        aliases = {
            "NY": "NEW_YORK",
            "NEWYORK": "NEW_YORK",
            "NEW-YORK": "NEW_YORK",
            "LON": "LONDON",
            "LDN": "LONDON",
            "TKY": "ASIA",
            "TOKYO": "ASIA",
            "REGULAR": "NEW_YORK",
        }
        kwargs["session"] = aliases.get(raw_session, raw_session)

    if tool_name == "add_indicator":
        inputs = kwargs.get("inputs")
        if not isinstance(inputs, dict):
            inputs = {}
        period = kwargs.pop("period", None)
        length = kwargs.pop("length", None)
        if period is not None:
            inputs.setdefault("period", period)
            inputs.setdefault("length", period)
        if length is not None:
            inputs.setdefault("length", length)
        if inputs:
            kwargs["inputs"] = inputs

    if tool_name == "draw":
        style = kwargs.get("style")
        if not isinstance(style, dict):
            style = {}
        if kwargs.get("line_width") is not None:
            style.setdefault("linewidth", kwargs.pop("line_width"))
        if kwargs.get("color") is not None:
            style.setdefault("color", kwargs.pop("color"))
        if "fill" in kwargs:
            fill_value = kwargs.pop("fill")
            if isinstance(fill_value, bool):
                style.setdefault("filled", fill_value)
            elif fill_value is not None:
                style.setdefault("fillColor", fill_value)
                style.setdefault("filled", True)
        if style:
            kwargs["style"] = style

    if "target_symbol" in param_names and not kwargs.get("target_symbol"):
        kwargs.pop("target_symbol", None)
    return kwargs
