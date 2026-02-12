from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..Guardrails.risk_gate import RiskGate
from ..Schema.agent_runtime import AgentPlan, PlanContext, ToolCall


TIMEFRAME_RE = re.compile(r"\b(1m|3m|5m|15m|30m|1h|4h|1d|1w)\b", re.IGNORECASE)
SYMBOL_RE = re.compile(r"\$?([A-Za-z]{2,12})(?:[-_/](USD|USDT|PERP))?\b", re.IGNORECASE)
USD_AMOUNT_RE = re.compile(r"\$?\s*(\d+(?:\.\d+)?)\s*(usd|usdt|\$)?\b", re.IGNORECASE)
LEVERAGE_RE = re.compile(r"\b(\d{1,3})\s*x\b", re.IGNORECASE)
PRICE_RE = re.compile(r"\b(?:at|price|entry|limit|stop)\s*\$?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
TP_TARGET_RE = re.compile(
    r"\b(?:tp|take\s*profit)\b\s*(?:to|=|:)?\s*(-?\d+(?:\.\d+)?\s*(?:%|USD|\$)?)",
    re.IGNORECASE,
)
SL_TARGET_RE = re.compile(
    r"\b(?:sl|stop\s*loss)\b\s*(?:to|=|:)?\s*(-?\d+(?:\.\d+)?\s*(?:%|USD|\$)?)",
    re.IGNORECASE,
)
LOOKBACK_RE = re.compile(
    r"\b(?:lookback|window|last|ambil|pakai|use|call)?\s*(\d{1,3})\s*(?:candle|candles|bar|bars)\b",
    re.IGNORECASE,
)

PAIR_RE = re.compile(r"\b([A-Za-z]{2,12})\s*[-_/]\s*([A-Za-z]{2,12})\b", re.IGNORECASE)
DOLLAR_TICKER_RE = re.compile(r"\$([A-Za-z]{2,12})\b")
WORD_RE = re.compile(r"\b[A-Za-z]{2,16}\b")

NUMBER_WORD_LOOKBACK: Dict[str, int] = {
    "dua": 2,
    "tiga": 3,
    "empat": 4,
    "lima": 5,
    "enam": 6,
    "tujuh": 7,
    "delapan": 8,
    "sembilan": 9,
    "sepuluh": 10,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

SYMBOL_ALIASES: Dict[str, str] = {
    "btc": "BTC",
    "bitcoin": "BTC",
    "eth": "ETH",
    "ethereum": "ETH",
    "sol": "SOL",
    "solana": "SOL",
    "soll": "SOL",
    "xrp": "XRP",
    "doge": "DOGE",
    "ada": "ADA",
    "avax": "AVAX",
    "arb": "ARB",
    "link": "LINK",
    "sui": "SUI",
    "hype": "HYPE",
    "bnb": "BNB",
    "bera": "BERA",
    "ark": "ARK",
}

SYMBOL_STOPWORDS: Set[str] = {
    "USD",
    "USDT",
    "PERP",
    "LONG",
    "SHORT",
    "TP",
    "SL",
    "PRICE",
    "MARKET",
    "TRADE",
    "ORDER",
    "ENTRY",
    "LIMIT",
    "STOP",
    "PLEASE",
    "HELLO",
    "HI",
    "CHECK",
    "OSTIUM",
    "HYPERLIQUID",
}

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

RWA_BASE_CODES: Set[str] = {
    "XAU",
    "XAG",
    "XPD",
    "XPT",
    "CL",
    "HG",
    "DAX",
    "DJI",
    "FTSE",
    "HSI",
    "NDX",
    "NIK",
    "SPX",
}

RWA_EQUITY_CODES: Set[str] = {
    "AAPL",
    "MSFT",
    "GOOG",
    "GOOGL",
    "AMZN",
    "TSLA",
    "META",
    "NFLX",
    "NVDA",
    "AMD",
    "COIN",
    "PLTR",
}


def _normalize_timeframe(raw: Optional[str]) -> str:
    if not raw:
        return "1H"
    value = raw.strip().upper()
    replacements = {
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
    return replacements.get(value, value)


def _canonical_base(
    token: str,
    prefer_fuzzy: bool = True,
    allow_reserved: bool = False,
    allow_generic_lower: bool = False,
) -> Optional[str]:
    t = (token or "").strip().replace("$", "")
    if not t:
        return None
    low = t.lower()
    if low in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[low]
    up = t.upper()
    if not allow_reserved and up in SYMBOL_STOPWORDS:
        return None
    if t.isupper() and 2 <= len(t) <= 12:
        return up
    if allow_generic_lower and t.isalpha() and 2 <= len(t) <= 12:
        return up
    if prefer_fuzzy and 3 <= len(low) <= 6:
        close = difflib.get_close_matches(low, list(SYMBOL_ALIASES.keys()), n=1, cutoff=0.84)
        if close:
            return SYMBOL_ALIASES[close[0]]
    return None


def _append_symbol(symbols: List[str], symbol: Optional[str], max_symbols: int) -> None:
    if not symbol:
        return
    if symbol in symbols:
        return
    if len(symbols) >= max_symbols:
        return
    symbols.append(symbol)


def _extract_symbols(text: str, max_symbols: int = 4) -> List[str]:
    raw_text = text or ""
    if not raw_text.strip():
        return []

    symbols: List[str] = []

    for match in PAIR_RE.finditer(raw_text):
        base = _canonical_base(
            match.group(1), prefer_fuzzy=True, allow_reserved=True, allow_generic_lower=True
        ) or (match.group(1) or "").upper()
        quote = _canonical_base(
            match.group(2), prefer_fuzzy=False, allow_reserved=True, allow_generic_lower=True
        ) or (match.group(2) or "").upper()
        if not base or not quote:
            continue
        normalized = f"{base}-USD" if quote in {"USD", "USDT"} else f"{base}-{quote}"
        _append_symbol(symbols, normalized, max_symbols=max_symbols)

    for match in DOLLAR_TICKER_RE.finditer(raw_text):
        base = _canonical_base(match.group(1), prefer_fuzzy=True) or (match.group(1) or "").upper()
        if base in SYMBOL_STOPWORDS:
            continue
        _append_symbol(symbols, f"{base}-USD", max_symbols=max_symbols)

    for token in WORD_RE.findall(raw_text):
        base = _canonical_base(token, prefer_fuzzy=True)
        if base:
            _append_symbol(symbols, f"{base}-USD", max_symbols=max_symbols)

    for match in SYMBOL_RE.finditer(raw_text):
        raw_base = (match.group(1) or "").strip()
        base = _canonical_base(
            raw_base,
            prefer_fuzzy=True,
            allow_reserved=True,
            allow_generic_lower=False,
        )
        if not base:
            if raw_base.isupper() and raw_base.isalpha():
                base = raw_base.upper()
            else:
                continue
        quote = (match.group(2) or "").upper()
        if base in SYMBOL_STOPWORDS and base not in FIAT_CODES:
            continue
        if not quote and len(base) == 6 and base[:3] in FIAT_CODES and base[3:] in FIAT_CODES:
            _append_symbol(symbols, f"{base[:3]}-{base[3:]}", max_symbols=max_symbols)
            continue
        if quote:
            normalized = f"{base}-USD" if quote in {"USD", "USDT"} else f"{base}-{quote}"
            _append_symbol(symbols, normalized, max_symbols=max_symbols)
            continue
        if base in FIAT_CODES:
            continue
        _append_symbol(symbols, f"{base}-USD", max_symbols=max_symbols)

    return symbols


def _extract_symbol(text: str) -> Optional[str]:
    symbols = _extract_symbols(text, max_symbols=1)
    return symbols[0] if symbols else None


def _extract_symbol_relaxed(text: str) -> Optional[str]:
    raw_text = text or ""
    if not raw_text.strip():
        return None

    for match in PAIR_RE.finditer(raw_text):
        base = (match.group(1) or "").upper()
        quote = (match.group(2) or "").upper()
        if not base or not quote:
            continue
        if quote in {"USD", "USDT"}:
            return f"{base}-USD"
        return f"{base}-{quote}"

    tokens = WORD_RE.findall(raw_text)
    for token in reversed(tokens):
        up = token.upper()
        if up in SYMBOL_STOPWORDS or up in FIAT_CODES:
            continue
        if 2 <= len(up) <= 12:
            return f"{up}-USD"
    return None


def _normalize_symbol_from_tool_state(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip().upper().replace("/", "-")
    if not value:
        return None
    if "-" in value:
        base, quote = value.split("-", 1)
        if not base:
            return None
        if quote in {"USD", "USDT"}:
            return f"{base}-USD"
        return f"{base}-{quote}"
    if value in {"USD", "USDT"}:
        return None
    return f"{value}-USD"


def _infer_asset_type_from_symbol(symbol: Optional[str]) -> str:
    if not symbol:
        return "crypto"
    value = str(symbol).strip().upper().replace("/", "-").replace("_", "-")
    if not value:
        return "crypto"

    if "-" not in value:
        if len(value) == 6 and value[:3] in FIAT_CODES and value[3:] in FIAT_CODES:
            return "rwa"
        return "crypto"

    base, quote = value.split("-", 1)
    if base in FIAT_CODES:
        return "rwa"
    if quote in FIAT_CODES and quote not in {"USD", "USDT"}:
        return "rwa"
    if base in RWA_BASE_CODES:
        return "rwa"
    if base in RWA_EQUITY_CODES:
        return "rwa"
    return "crypto"


def _symbol_to_tool_symbol(symbol: Optional[str]) -> Optional[str]:
    if not symbol:
        return None
    value = str(symbol).strip().upper().replace("/", "-").replace("_", "-")
    if not value:
        return None

    if "-" not in value:
        if len(value) == 6 and value[:3] in FIAT_CODES and value[3:] in FIAT_CODES:
            return f"{value[:3]}-{value[3:]}"
        return value

    base, quote = value.split("-", 1)
    if quote in {"USD", "USDT"} and base not in FIAT_CODES:
        return base
    return f"{base}-{quote}"


def _infer_requested_chart_source(text: str) -> Optional[str]:
    lower = (text or "").lower()
    if not lower:
        return None
    if "ostium" in lower or "rwa" in lower:
        return "ostium"
    if "hyperliquid" in lower:
        return "hyperliquid"
    return None


def _looks_like_symbol_only_message(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.fullmatch(r"\$?[A-Za-z]{2,12}", raw):
        return True
    if re.fullmatch(r"[A-Za-z]{2,12}\s*[-_/]\s*[A-Za-z]{2,12}", raw):
        return True
    return False


def _contains_any(text: str, words: List[str]) -> bool:
    lower = (text or "").lower()
    return any(w in lower for w in words)


def _is_smalltalk(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower:
        return True
    if _extract_symbol(text):
        return False
    smalltalk_terms = ["hi", "hello", "hey", "gm", "good morning", "good evening", "how are you"]
    market_terms = [
        "price", "btc", "eth", "sol", "solana", "soll", "market", "chart", "trade", "long", "short",
        "analysis", "indicator", "order", "funding", "orderbook", "news", "sentiment",
    ]
    return _contains_any(lower, smalltalk_terms) and not _contains_any(lower, market_terms)


def _extract_side(text: str) -> Optional[str]:
    t = (text or "").lower()
    if any(x in t for x in ["buy", "long"]):
        return "buy"
    if any(x in t for x in ["sell", "short"]):
        return "sell"
    return None


def _extract_order_type(text: str) -> str:
    t = (text or "").lower()
    if "stop limit" in t:
        return "stop_limit"
    if "stop market" in t:
        return "stop_market"
    if "limit" in t:
        return "limit"
    return "market"


def _extract_amount_usd(text: str) -> Optional[float]:
    for match in USD_AMOUNT_RE.finditer(text or ""):
        raw = match.group(1)
        unit = (match.group(2) or "").lower()
        try:
            value = float(raw)
        except Exception:
            continue
        if value <= 0:
            continue
        if unit in {"usd", "usdt", "$"}:
            return value
    for match in USD_AMOUNT_RE.finditer(text or ""):
        try:
            value = float(match.group(1))
            if value > 0:
                return value
        except Exception:
            continue
    return None


def _extract_leverage(text: str) -> int:
    match = LEVERAGE_RE.search(text or "")
    if not match:
        return 1
    try:
        lev = int(match.group(1))
        return lev if lev > 0 else 1
    except Exception:
        return 1


def _extract_prices(text: str) -> Dict[str, Optional[float]]:
    t = (text or "").lower()
    value_map: Dict[str, Optional[float]] = {"limit_price": None, "stop_price": None}

    limit_m = re.search(r"\blimit\s*\$?\s*(\d+(?:\.\d+)?)\b", t, re.IGNORECASE)
    stop_m = re.search(r"\bstop(?:\s*loss)?\s*\$?\s*(\d+(?:\.\d+)?)\b", t, re.IGNORECASE)
    if limit_m:
        try:
            value_map["limit_price"] = float(limit_m.group(1))
        except Exception:
            pass
    if stop_m:
        try:
            value_map["stop_price"] = float(stop_m.group(1))
        except Exception:
            pass

    if value_map["limit_price"] is None and value_map["stop_price"] is None:
        pm = PRICE_RE.search(t)
        if pm:
            try:
                value_map["limit_price"] = float(pm.group(1))
            except Exception:
                pass
    return value_map


def _normalize_tpsl_input_token(raw: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
    token = str(raw or "").strip().upper().replace(" ", "")
    if not token:
        return None, None

    if token.endswith("%"):
        try:
            pct = float(token[:-1])
        except Exception:
            return None, None
        if pct <= 0:
            return None, None
        return None, pct

    numeric_token = token.replace("USD", "").replace("$", "")
    try:
        value = float(numeric_token)
    except Exception:
        return None, None
    if value <= 0:
        return None, None
    if value.is_integer():
        return str(int(value)), None
    return str(value), None


def _extract_tpsl_targets(text: str) -> Dict[str, Optional[Any]]:
    tp_value: Optional[str] = None
    sl_value: Optional[str] = None
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None

    tp_match = TP_TARGET_RE.search(text or "")
    if tp_match:
        val, pct = _normalize_tpsl_input_token(tp_match.group(1))
        tp_value = val
        tp_pct = pct

    sl_match = SL_TARGET_RE.search(text or "")
    if sl_match:
        val, pct = _normalize_tpsl_input_token(sl_match.group(1))
        sl_value = val
        sl_pct = pct

    return {
        "tp": tp_value,
        "sl": sl_value,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
    }


def _extract_lookback_candles(text: str, default: int = 7) -> int:
    raw_text = text or ""
    match = LOOKBACK_RE.search(raw_text)
    if match:
        try:
            value = int(match.group(1))
            return max(2, min(value, 500))
        except Exception:
            pass

    lowered = raw_text.lower()
    for word, value in NUMBER_WORD_LOOKBACK.items():
        if re.search(rf"\b{re.escape(word)}\s*(?:candle|candles|bar|bars)\b", lowered):
            return max(2, min(int(value), 500))

    return max(2, min(int(default), 500))


def _append_tool_call(plan: AgentPlan, name: str, args: Dict[str, Any], reason: str) -> None:
    plan.tool_calls.append(ToolCall(name=name, args=args, reason=reason))


def _finalize_tool_calls(plan: AgentPlan, max_calls: int = 6) -> None:
    unique: List[ToolCall] = []
    seen: Set[Tuple[str, str]] = set()
    for call in plan.tool_calls:
        key = (call.name, json.dumps(call.args, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)
    plan.tool_calls = unique[:max_calls]


def build_plan(
    user_message: str,
    history: Optional[List[Dict[str, Any]]] = None,
    tool_states: Optional[Dict[str, Any]] = None,
) -> AgentPlan:
    _ = history
    text = user_message or ""
    tool_states = tool_states or {}

    tool_state_symbol = _normalize_symbol_from_tool_state(
        tool_states.get("market_symbol") or tool_states.get("market") or tool_states.get("market_display")
    )
    extracted_symbols = _extract_symbols(text, max_symbols=4)
    extracted_symbol = extracted_symbols[0] if extracted_symbols else None
    symbol_hint_terms = [
        "check",
        "price",
        "quote",
        "about",
    ]
    if not extracted_symbol and _contains_any(text, symbol_hint_terms):
        extracted_symbol = _extract_symbol_relaxed(text)
        if extracted_symbol:
            extracted_symbols = [extracted_symbol, *[item for item in extracted_symbols if item != extracted_symbol]]
    symbol = extracted_symbol or tool_state_symbol
    additional_symbols = [item for item in extracted_symbols if item and item != symbol]
    requested_chart_source = _infer_requested_chart_source(text)

    timeframe_match = TIMEFRAME_RE.search(text)
    default_tf = None
    if isinstance(tool_states.get("timeframe"), str):
        default_tf = tool_states.get("timeframe")
    elif isinstance(tool_states.get("timeframe"), list) and tool_states.get("timeframe"):
        default_tf = tool_states["timeframe"][0]
    timeframe = _normalize_timeframe(timeframe_match.group(1) if timeframe_match else default_tf)

    wants_execution = RiskGate.wants_execution(text)
    wants_price = _contains_any(text, ["price", "last price", "quote", "mark price", "current price"])
    wants_news = _contains_any(text, ["news", "headline", "macro", "fomc", "cpi"])
    wants_sentiment = _contains_any(text, ["sentiment", "twitter", "x.com", "x "])
    wants_whales = _contains_any(text, ["whale", "onchain", "large order flow", "smart money"])
    wants_candles = _contains_any(text, ["candle", "candles", "ohlc", "kline"])
    wants_high_low_levels = _contains_any(
        text,
        ["high low", "high/low", "support", "resistance", "s/r", "sbr", "s n r"],
    )
    wants_orderbook = _contains_any(text, ["orderbook", "order book", "depth", "bid ask"])
    wants_funding = _contains_any(text, ["funding", "funding rate"])
    wants_stats = _contains_any(text, ["24h", "high low", "volume", "ticker stats", "stats"])
    wants_chainlink = _contains_any(text, ["chainlink", "oracle price"])
    wants_patterns = _contains_any(text, ["pattern", "patterns"])
    wants_indicator_values = _contains_any(text, ["indicator values", "indicator value", "indicator reading"])
    wants_technical_summary = _contains_any(text, ["technical summary", "summarize technical", "summary technical"])
    wants_distribution = _contains_any(text, ["token distribution", "holder distribution", "distribution"])
    wants_active_indicators = _contains_any(text, ["active indicator", "active indicators", "current indicators"])
    wants_research = _contains_any(text, [
        "research", "cross-market", "multi-market", "compare market", "market comparison",
        "across markets", "both markets", "hyperliquid and ostium", "ostium and hyperliquid",
        "scan market", "market overview", "top movers", "broad scan", "screening",
        "compare price", "price comparison",
    ])
    wants_chart_capture = _contains_any(text, ["screenshot", "snapshot", "capture chart"])
    wants_cursor_inspect = _contains_any(text, ["inspect cursor", "cursor data"])
    wants_reset_view = _contains_any(text, ["reset view", "reset chart"])
    wants_focus_latest = _contains_any(text, ["focus latest", "latest candle"])
    wants_set_timeframe = _contains_any(text, ["set timeframe", "change timeframe"])
    wants_set_symbol = _contains_any(text, ["set symbol", "change symbol", "switch symbol"])
    wants_clear_indicators = _contains_any(
        text,
        [
            "clear indicators",
            "clear indicator",
            "clear all indicators",
            "delete all indicators",
            "remove all indicators",

            "reset indicators",
        ],
    )
    wants_remove_indicator = _contains_any(
        text,
        [
            "remove indicator",
            "delete indicator",

        ],
    ) and not wants_clear_indicators
    wants_drawing_guidance = _contains_any(text, [
        "draw", "trendline", "fibonacci", "fib", "rectangle", "drawing tool",
        "mark level", "mark zone", "horizontal line", "support line", "resistance line",
        "channel", "pitchfork", "gann", "elliott", "arrow",
        "fib retracement", "fib extension", "fib trend",
        "long position", "short position", "price range",
    ])
    wants_trade_guidance = _contains_any(text, [
        "stop loss", "take profit", "risk management", "position sizing",
        "risk reward", "risk/reward", "r/r", "rrr", "money management",
        "position size", "lot size", "margin", "leverage management",
        "trailing stop", "breakeven", "move sl", "tighten stop",
        "partial take profit", "scale out", "scale in",
    ])
    wants_market_guidance = _contains_any(text, [
        "market context", "market regime", "trend or range",
        "market structure", "market phase", "accumulation", "distribution",
    ])
    wants_strategy_guidance = _contains_any(text, [
        "strategy", "playbook", "best setup", "trading plan",
        "approach", "methodology", "system",
    ])
    wants_technical = _contains_any(
        text,
        ["technical", "rsi", "macd", "support", "resistance", "trend", "indicator", "setup", "chart"],
    )
    indicator_management_only = (
        (wants_clear_indicators or wants_remove_indicator)
        and not _contains_any(
            text,
            [
                "analysis",
                "setup",
                "trend",
                "signal",
                "entry",
                "tp",
                "sl",
                "risk",
                "market context",
            ],
        )
    )
    if indicator_management_only:
        wants_technical = False
        wants_price = False
    mentions_tpsl = _contains_any(text, ["tp", "sl", "take profit", "stop loss", "tpsl"])
    wants_tpsl_adjust = mentions_tpsl and _contains_any(
        text,
        [
            "adjust",
            "update",
            "change",
            "move",
            "set tp",
            "set sl",
            "tighten",
            "widen",
            "trail",
        ],
    )
    wants_tpsl_adjust_all = wants_tpsl_adjust and _contains_any(
        text,
        ["all positions", "all open positions", "all trades", "all symbols"],
    )
    tpsl_targets = _extract_tpsl_targets(text)
    lookback_candles = _extract_lookback_candles(text, default=7)
    has_symbol_hint_request = _contains_any(
        text,
        ["check", "price", "quote", "about"],
    )
    if symbol and not any(
        [
            wants_execution,
            wants_news,
            wants_sentiment,
            wants_whales,
            wants_candles,
            wants_high_low_levels,
            wants_orderbook,
            wants_funding,
            wants_stats,
            wants_chainlink,
            wants_patterns,
            wants_indicator_values,
            wants_technical_summary,
            wants_distribution,
            wants_active_indicators,
            wants_drawing_guidance,
            wants_trade_guidance,
            wants_market_guidance,
            wants_strategy_guidance,
            wants_technical,
            wants_research,
        ]
    ) and (has_symbol_hint_request or _looks_like_symbol_only_message(text)):
        wants_price = True

    side = _extract_side(text)
    order_type = _extract_order_type(text)
    amount_usd = _extract_amount_usd(text) if wants_execution else None
    leverage = _extract_leverage(text) if wants_execution else 1
    prices = _extract_prices(text)
    write_enabled = bool(tool_states.get("write"))
    symbol_changed = bool(symbol and tool_state_symbol and symbol != tool_state_symbol)
    auto_set_symbol = symbol_changed and bool(extracted_symbol)

    selected_indicators: List[str] = []
    raw_indicators = tool_states.get("indicators")
    if isinstance(raw_indicators, list):
        selected_indicators = [
            str(item).strip()
            for item in raw_indicators
            if isinstance(item, str) and str(item).strip()
        ]

    indicator_name_hints = {
        "rsi": "RSI",
        "macd": "MACD",
        "stoch": "Stoch",
        "stochastic": "Stoch",
        "ema": "EMA",
        "sma": "SMA",
        "vwap": "VWAP",
        "bb": "Bollinger Bands",
        "bollinger": "Bollinger Bands",
        "atr": "ATR",
        "adx": "ADX",
        "ichimoku": "Ichimoku",
        "supertrend": "SuperTrend",
        "volume": "Volume",
    }
    text_lower = (text or "").lower()
    for key, label in indicator_name_hints.items():
        if key in text_lower and label not in selected_indicators:
            selected_indicators.append(label)

    context = PlanContext(
        symbol=symbol,
        timeframe=timeframe,
        requested_execution=wants_execution,
        requested_news=wants_news,
        requested_sentiment=wants_sentiment,
        requested_whales=wants_whales,
        side=side,
        order_type=order_type,
        amount_usd=amount_usd,
        leverage=leverage,
        limit_price=prices.get("limit_price"),
        stop_price=prices.get("stop_price"),
    )

    intent = "execution" if (wants_execution or wants_tpsl_adjust) else "analysis"
    plan = AgentPlan(intent=intent, context=context)

    if _is_smalltalk(text):
        return plan

    if not symbol and (wants_execution or wants_technical) and not wants_tpsl_adjust_all:
        plan.warnings.append("No symbol detected. Provide a ticker (example: BTC, ETH, SOL).")
        return plan

    if wants_execution and side is None:
        plan.warnings.append("Execution intent detected but side is unclear. Specify buy/long or sell/short.")

    if wants_execution and amount_usd is None:
        plan.warnings.append("Execution intent detected but amount is missing. Specify size in USD.")

    if wants_tpsl_adjust and (
        tpsl_targets.get("tp") is None
        and tpsl_targets.get("sl") is None
        and tpsl_targets.get("tp_pct") is None
        and tpsl_targets.get("sl_pct") is None
    ):
        plan.warnings.append(
            "TP/SL adjustment intent detected but no TP/SL target value found. "
            "Example: `adjust TP 71200 SL 68900` or `adjust all TP 3% SL 1.5%`."
        )

    if wants_execution and additional_symbols:
        plan.warnings.append(
            f"Multiple symbols detected ({', '.join([symbol] + additional_symbols)}). "
            f"Execution will use primary symbol {symbol} only."
        )

    if wants_tpsl_adjust_all and not symbol:
        all_args: Dict[str, Any] = {}
        if tpsl_targets.get("tp") is not None:
            all_args["tp"] = tpsl_targets.get("tp")
        if tpsl_targets.get("sl") is not None:
            all_args["sl"] = tpsl_targets.get("sl")
        if tpsl_targets.get("tp_pct") is not None:
            all_args["tp_pct"] = tpsl_targets.get("tp_pct")
        if tpsl_targets.get("sl_pct") is not None:
            all_args["sl_pct"] = tpsl_targets.get("sl_pct")
        if all_args:
            _append_tool_call(
                plan,
                name="adjust_all_positions_tpsl",
                args=all_args,
                reason="Bulk adjust TP/SL across open positions per user request.",
            )

    # Research agent: cross-market / multi-market tools
    if wants_research:
        if extracted_symbols and len(extracted_symbols) > 1:
            # Multiple symbols -> compare_markets
            _append_tool_call(
                plan,
                name="compare_markets",
                args={"symbols": extracted_symbols[:5], "timeframe": timeframe},
                reason="Compare multiple symbols across Hyperliquid + Ostium markets.",
            )
        elif symbol:
            # Single symbol -> research_market (deep dive)
            _append_tool_call(
                plan,
                name="research_market",
                args={"symbol": _symbol_to_tool_symbol(symbol) or symbol, "timeframe": timeframe},
                reason=f"Research {symbol} across all available markets (Hyperliquid + Ostium).",
            )
        else:
            # No symbol -> scan_market_overview
            _append_tool_call(
                plan,
                name="scan_market_overview",
                args={"asset_class": "all"},
                reason="Scan all available markets for top movers and opportunities.",
            )

    if symbol:
        inferred_symbol_asset_type = _infer_asset_type_from_symbol(symbol)
        inferred_symbol_source = "ostium" if inferred_symbol_asset_type == "rwa" else "hyperliquid"
        target_chart_source = requested_chart_source or inferred_symbol_source

        needs_market_data = any([
            wants_price,
            wants_execution,
            wants_technical,
            wants_news,
            wants_sentiment,
            wants_whales,
            wants_candles,
            wants_high_low_levels,
            wants_orderbook,
            wants_funding,
            wants_stats,
            wants_chainlink,
            wants_patterns,
            wants_indicator_values,
            wants_technical_summary,
            wants_distribution,
            wants_active_indicators,
            wants_chart_capture,
            wants_cursor_inspect,
            wants_reset_view,
            wants_focus_latest,
            wants_set_timeframe,
        ])

        # Auto chart symbol sync when user requests a different symbol than active chip/state.
        if auto_set_symbol:
            if write_enabled:
                source_symbol = tool_state_symbol or symbol
                set_symbol_args: Dict[str, Any] = {
                    "symbol": source_symbol,
                    "target_symbol": symbol,
                }
                if requested_chart_source:
                    set_symbol_args["target_source"] = target_chart_source
                _append_tool_call(
                    plan,
                    name="set_symbol",
                    args=set_symbol_args,
                    reason=f"Switch chart from {tool_state_symbol} to requested symbol {symbol} before analysis.",
                )
            elif needs_market_data:
                plan.warnings.append(
                    f"Requested symbol differs from active chart ({tool_state_symbol} -> {symbol}). "
                    "Enable 'Allow Write' to sync chart symbol automatically."
                )

        tool_symbol = _symbol_to_tool_symbol(symbol) or symbol
        if requested_chart_source == "ostium":
            asset_type = "rwa"
        elif requested_chart_source == "hyperliquid":
            asset_type = "crypto"
        else:
            asset_type = inferred_symbol_asset_type
        is_crypto_asset = asset_type == "crypto"

        if any([
            wants_price,
            wants_execution,
            wants_technical,
            wants_news,
            wants_sentiment,
            wants_whales,
            wants_candles,
            wants_high_low_levels,
            wants_orderbook,
            wants_funding,
            wants_stats,
            wants_chainlink,
        ]):
            _append_tool_call(
                plan,
                name="get_price",
                args={"symbol": tool_symbol, "asset_type": asset_type},
                reason="Fetch live reference price for the active symbol.",
            )
            for extra_symbol in additional_symbols[:3]:
                extra_tool_symbol = _symbol_to_tool_symbol(extra_symbol) or extra_symbol
                extra_asset_type = _infer_asset_type_from_symbol(extra_symbol)
                _append_tool_call(
                    plan,
                    name="get_price",
                    args={"symbol": extra_tool_symbol, "asset_type": extra_asset_type},
                    reason=f"Fetch live reference price for additional requested symbol {extra_symbol}.",
                )

        if wants_candles:
            _append_tool_call(
                plan,
                name="get_candles",
                args={"symbol": tool_symbol, "timeframe": timeframe, "limit": 100, "asset_type": asset_type},
                reason="Fetch candle structure for timeframe-aware analysis.",
            )
        if wants_high_low_levels:
            _append_tool_call(
                plan,
                name="get_high_low_levels",
                args={
                    "symbol": tool_symbol,
                    "timeframe": timeframe,
                    "lookback": lookback_candles,
                    "limit": max(lookback_candles, 50),
                    "asset_type": asset_type,
                },
                reason=(
                    f"Compute rolling high/low (support/resistance) using lookback={lookback_candles} candles."
                ),
            )
        if wants_orderbook:
            if is_crypto_asset:
                _append_tool_call(
                    plan,
                    name="get_orderbook",
                    args={"symbol": tool_symbol, "asset_type": asset_type},
                    reason="Inspect bid/ask depth and imbalance.",
                )
            else:
                plan.warnings.append(
                    "Orderbook depth is only available for crypto markets. Skipping orderbook step for this symbol."
                )
        if wants_funding:
            if is_crypto_asset:
                _append_tool_call(
                    plan,
                    name="get_funding_rate",
                    args={"symbol": tool_symbol, "asset_type": asset_type},
                    reason="Check funding pressure for perp positioning.",
                )
            else:
                plan.warnings.append(
                    "Funding-rate context is not available for this non-crypto market. Skipping funding step."
                )
        if wants_stats:
            _append_tool_call(
                plan,
                name="get_ticker_stats",
                args={"symbol": tool_symbol, "asset_type": asset_type},
                reason="Read 24h ticker context (volume/high/low/change).",
            )
        if wants_chainlink:
            _append_tool_call(
                plan,
                name="get_chainlink_price",
                args={"symbol": tool_symbol},
                reason="Cross-check reference oracle pricing.",
            )

        if selected_indicators and not wants_remove_indicator and not wants_clear_indicators:
            if write_enabled:
                for indicator_name in selected_indicators[:2]:
                    _append_tool_call(
                        plan,
                        name="add_indicator",
                        args={"symbol": symbol, "name": indicator_name, "inputs": {}, "force_overlay": True},
                        reason=f"Add selected indicator `{indicator_name}` to chart.",
                    )
            else:
                plan.warnings.append(
                    "Indicators selected, but write mode is disabled. Enable 'Allow Write' to add indicators on chart."
                )
            _append_tool_call(
                plan,
                name="get_active_indicators",
                args={"symbol": symbol, "timeframe": timeframe},
                reason="Read back active indicators from chart context.",
            )
        elif wants_active_indicators:
            _append_tool_call(
                plan,
                name="get_active_indicators",
                args={"symbol": symbol, "timeframe": timeframe},
                reason="Inspect currently active chart indicators.",
            )

        if wants_clear_indicators:
            if write_enabled:
                _append_tool_call(
                    plan,
                    name="clear_indicators",
                    args={"symbol": symbol},
                    reason="Clear all active indicators from chart as requested.",
                )
            else:
                plan.warnings.append(
                    "Clear indicators requested, but write mode is disabled. Enable 'Allow Write' first."
                )
        elif wants_remove_indicator:
            if write_enabled:
                if selected_indicators:
                    for indicator_name in selected_indicators[:2]:
                        _append_tool_call(
                            plan,
                            name="remove_indicator",
                            args={"symbol": symbol, "name": indicator_name},
                            reason=f"Remove indicator `{indicator_name}` from chart.",
                        )
                else:
                    plan.warnings.append(
                        "Remove indicator requested, but indicator name not detected. Mention indicator name (e.g., RSI/MACD)."
                    )
            else:
                plan.warnings.append(
                    "Remove indicator requested, but write mode is disabled. Enable 'Allow Write' first."
                )

        # When drawing is requested with a symbol, ensure reference data is fetched first
        if wants_drawing_guidance and symbol:
            # Ensure high/low levels are available as reference for drawing coordinates
            if not wants_high_low_levels:
                _append_tool_call(
                    plan,
                    name="get_high_low_levels",
                    args={
                        "symbol": tool_symbol,
                        "timeframe": timeframe,
                        "lookback": lookback_candles,
                        "limit": max(lookback_candles, 50),
                        "asset_type": asset_type,
                    },
                    reason="Fetch reference price levels before drawing operations (coordinates must be real).",
                )
            # Extract specific drawing tool for targeted guidance
            drawing_tool_type = "trendline"
            drawing_kw_map = {
                "fib": "fib_retracement", "fibonacci": "fib_retracement",
                "channel": "parallel_channel", "pitchfork": "pitchfork",
                "gann": "gann_box", "elliott": "elliott_impulse_wave",
                "rectangle": "rectangle", "horizontal": "horizontal_line",
                "arrow": "arrow", "support line": "horizontal_line",
                "resistance line": "horizontal_line",
            }
            text_lower_for_draw = (text or "").lower()
            for kw, tool_type in drawing_kw_map.items():
                if kw in text_lower_for_draw:
                    drawing_tool_type = tool_type
                    break
            _append_tool_call(
                plan,
                name="get_drawing_guidance",
                args={"tool_name": drawing_tool_type},
                reason=f"Retrieve drawing best practices for {drawing_tool_type}.",
            )

        if wants_technical or wants_execution:
            _append_tool_call(
                plan,
                name="get_technical_analysis",
                args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                reason="Compute technical context used for trade setup validation.",
            )
        if wants_patterns:
            _append_tool_call(
                plan,
                name="get_patterns",
                args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                reason="Extract pattern candidates from current market structure.",
            )
        if wants_indicator_values:
            _append_tool_call(
                plan,
                name="get_indicators",
                args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                reason="Fetch indicator values for quantitative confirmation.",
            )
        if wants_technical_summary:
            _append_tool_call(
                plan,
                name="get_technical_summary",
                args={"symbol": symbol, "timeframe": timeframe, "asset_type": asset_type},
                reason="Provide concise technical summary for decision support.",
            )

        if wants_whales:
            if is_crypto_asset:
                _append_tool_call(
                    plan,
                    name="get_whale_activity",
                    args={"symbol": tool_symbol, "min_size_usd": 100000},
                    reason="Check large-flow positioning before suggesting execution.",
                )
            else:
                plan.warnings.append(
                    "Whale-flow connector is configured for crypto only. Skipping whale-activity step."
                )
        if wants_distribution:
            if is_crypto_asset:
                _append_tool_call(
                    plan,
                    name="get_token_distribution",
                    args={"symbol": tool_symbol},
                    reason="Inspect holder/distribution concentration risk.",
                )
            else:
                plan.warnings.append(
                    "Token distribution analysis is crypto-specific. Skipping distribution step for this symbol."
                )

        if wants_news:
            _append_tool_call(
                plan,
                name="search_news",
                args={"query": f"{symbol} latest market news"},
                reason="Collect recent headlines relevant to current symbol.",
            )
        if wants_sentiment:
            _append_tool_call(
                plan,
                name="search_sentiment",
                args={"symbol": tool_symbol},
                reason="Collect social sentiment context for current symbol.",
            )

        has_write_intent = any([
            wants_set_timeframe,
            wants_set_symbol,
            wants_clear_indicators,
            wants_remove_indicator,
            wants_chart_capture,
            wants_cursor_inspect,
            wants_reset_view,
            wants_focus_latest,
            wants_drawing_guidance,
            bool(selected_indicators),
        ])
        if has_write_intent and not write_enabled:
            plan.warnings.append(
                "Chart action requested, but write mode is disabled. Enable 'Allow Write' to run TradingView commands."
            )
        elif write_enabled:
            if wants_set_timeframe:
                _append_tool_call(
                    plan,
                    name="set_timeframe",
                    args={"symbol": symbol, "timeframe": timeframe},
                    reason="Align chart timeframe with current request.",
                )
            if wants_set_symbol:
                source_symbol = tool_state_symbol or symbol
                set_symbol_args: Dict[str, Any] = {
                    "symbol": source_symbol,
                    "target_symbol": symbol,
                }
                if requested_chart_source:
                    set_symbol_args["target_source"] = target_chart_source
                _append_tool_call(
                    plan,
                    name="set_symbol",
                    args=set_symbol_args,
                    reason="Align chart symbol with current request.",
                )
            if wants_reset_view:
                _append_tool_call(
                    plan,
                    name="reset_view",
                    args={"symbol": symbol},
                    reason="Reset chart viewport before further inspection.",
                )
            if wants_focus_latest:
                _append_tool_call(
                    plan,
                    name="focus_latest",
                    args={"symbol": symbol},
                    reason="Jump to latest candles for real-time context.",
                )
            if wants_cursor_inspect:
                _append_tool_call(
                    plan,
                    name="inspect_cursor",
                    args={"symbol": symbol},
                    reason="Inspect OHLC/indicator values at cursor position.",
                )
            if wants_chart_capture:
                _append_tool_call(
                    plan,
                    name="capture_moment",
                    args={"symbol": symbol, "caption": "agent_snapshot"},
                    reason="Capture visual snapshot for context handoff.",
                )

        if wants_tpsl_adjust:
            if wants_tpsl_adjust_all:
                args: Dict[str, Any] = {}
                if tpsl_targets.get("tp") is not None:
                    args["tp"] = tpsl_targets.get("tp")
                if tpsl_targets.get("sl") is not None:
                    args["sl"] = tpsl_targets.get("sl")
                if tpsl_targets.get("tp_pct") is not None:
                    args["tp_pct"] = tpsl_targets.get("tp_pct")
                if tpsl_targets.get("sl_pct") is not None:
                    args["sl_pct"] = tpsl_targets.get("sl_pct")
                if args:
                    _append_tool_call(
                        plan,
                        name="adjust_all_positions_tpsl",
                        args=args,
                        reason="Bulk adjust TP/SL across open positions per user request.",
                    )
            else:
                args = {"symbol": symbol}
                if tpsl_targets.get("tp") is not None:
                    args["tp"] = tpsl_targets.get("tp")
                if tpsl_targets.get("sl") is not None:
                    args["sl"] = tpsl_targets.get("sl")
                if tpsl_targets.get("tp_pct") is not None:
                    args["tp"] = f"{tpsl_targets.get('tp_pct')}%"
                if tpsl_targets.get("sl_pct") is not None:
                    args["sl"] = f"{tpsl_targets.get('sl_pct')}%"
                if len(args) > 1:
                    _append_tool_call(
                        plan,
                        name="adjust_position_tpsl",
                        args=args,
                        reason="Adjust TP/SL for requested symbol position.",
                    )

    elif wants_news:
        _append_tool_call(
            plan,
            name="search_news",
            args={"query": text},
            reason="General macro/news request with no specific symbol.",
        )
    else:
        if wants_drawing_guidance:
            # Extract specific drawing tool from user message for targeted guidance
            drawing_tool_type = "trendline"  # default
            drawing_keywords_map = {
                "fib": "fib_retracement", "fibonacci": "fib_retracement",
                "channel": "parallel_channel", "pitchfork": "pitchfork",
                "gann": "gann_box", "elliott": "elliott_impulse_wave",
                "rectangle": "rectangle", "horizontal": "horizontal_line",
                "arrow": "arrow", "support line": "horizontal_line",
                "resistance line": "horizontal_line",
            }
            text_lower_draw = (text or "").lower()
            for kw, tool_type in drawing_keywords_map.items():
                if kw in text_lower_draw:
                    drawing_tool_type = tool_type
                    break
            _append_tool_call(
                plan,
                name="get_drawing_guidance",
                args={"tool_name": drawing_tool_type},
                reason=f"Retrieve drawing best practices for {drawing_tool_type} before chart actions.",
            )
        if wants_trade_guidance:
            # Extract specific trade management topic
            trade_topic = "stop loss"  # default
            trade_topic_map = {
                "position siz": "position sizing", "risk reward": "risk reward",
                "trailing": "trailing stop", "breakeven": "breakeven",
                "scale": "scaling", "partial": "partial take profit",
            }
            text_lower_trade = (text or "").lower()
            for kw, topic in trade_topic_map.items():
                if kw in text_lower_trade:
                    trade_topic = topic
                    break
            _append_tool_call(
                plan,
                name="get_trade_management_guidance",
                args={"topic": trade_topic},
                reason=f"Retrieve risk/trade management guidance for {trade_topic}.",
            )
        if wants_market_guidance:
            _append_tool_call(
                plan,
                name="get_market_context_guidance",
                args={},
                reason="Retrieve market context classification framework.",
            )
        if wants_strategy_guidance:
            _append_tool_call(
                plan,
                name="consult_strategy",
                args={"question": text},
                reason="Retrieve strategy guidance from knowledge base.",
            )

    _finalize_tool_calls(plan, max_calls=8)
    return plan

