"""
TradingView Action Tools

Write-mode chart actions with strict execution evidence support.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, Optional, List
import datetime

from .command_client import send_tradingview_command
try:
    from agent.Tools.http_client import get_http_client
except Exception:
    from backend.agent.Tools.http_client import get_http_client
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

from .verify import verify_tradingview_state


_INDICATOR_NAME_MAP = {
    "RSI": "Relative Strength Index",
    "Stoch": "Stochastic",
    "StochRSI": "Stochastic RSI",
    "CCI": "Commodity Channel Index",
    "MACD": "MACD",
    "MFI": "Money Flow Index",
    "ROC": "Rate Of Change",
    "TSI": "True Strength Index",
    "Williams %R": "Williams %R",
    "AO": "Awesome Oscillator",
    "KST": "Know Sure Thing",
    "EMA": "Moving Average Exponential",
    "SMA": "Moving Average",
    "WMA": "Moving Average Weighted",
    "HMA": "Hull Moving Average",
    "VWMA": "VWMA",
    "MA": "Moving Average",
    "Bollinger Bands": "Bollinger Bands",
    "BB": "Bollinger Bands",
    "SuperTrend": "SuperTrend",
    "Parabolic SAR": "Parabolic SAR",
    "SAR": "Parabolic SAR",
    "Ichimoku": "Ichimoku Cloud",
    "ADX": "Average Directional Index",
    "DMI": "Directional Movement",
    "Mass Index": "Mass Index",
    "ATR": "Average True Range",
    "Keltner": "Keltner Channels",
    "Donchian": "Donchian Channels",
    "HV": "Historical Volatility",
    "OBV": "On Balance Volume",
    "VWAP": "VWAP",
    "VPVR": "Volume Profile Visible Range",
    "VPFR": "Volume Profile Fixed Range",
    "Volume": "Volume",
    "CMF": "Chaikin Money Flow",
    "EOM": "Ease Of Movement",
}

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")


def _norm_indicator_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _to_finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed:  # NaN
        return None
    if parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _normalize_trade_tripwire_levels(
    *,
    side: str,
    entry: Any,
    sl: Any,
    tp: Any,
    validation: Any,
    invalidation: Any,
) -> tuple[Optional[float], Optional[float]]:
    """
    Keep validation/invalidation aligned with side semantics:
    - long: validation above entry, invalidation below entry
    - short: validation below entry, invalidation above entry
    """
    side_norm = str(side or "").strip().lower()
    is_long = side_norm in {"buy", "long"}
    is_short = side_norm in {"sell", "short"}

    entry_level = _to_finite_float(entry)
    sl_level = _to_finite_float(sl)
    tp_level = _to_finite_float(tp)
    validation_level = _to_finite_float(validation)
    invalidation_level = _to_finite_float(invalidation)

    if validation_level is None and tp_level is not None:
        validation_level = tp_level
    if invalidation_level is None and sl_level is not None:
        invalidation_level = sl_level

    if entry_level is None or not (is_long or is_short):
        return validation_level, invalidation_level

    def _is_validation_ok(value: Optional[float]) -> bool:
        if value is None:
            return True
        return value > entry_level if is_long else value < entry_level

    def _is_invalidation_ok(value: Optional[float]) -> bool:
        if value is None:
            return True
        return value < entry_level if is_long else value > entry_level

    # If both were provided but clearly reversed around entry, swap once.
    if validation_level is not None and invalidation_level is not None:
        if is_long and validation_level < entry_level < invalidation_level:
            validation_level, invalidation_level = invalidation_level, validation_level
        elif is_short and validation_level > entry_level > invalidation_level:
            validation_level, invalidation_level = invalidation_level, validation_level

    if not _is_validation_ok(validation_level) and _is_validation_ok(tp_level):
        validation_level = tp_level
    if not _is_invalidation_ok(invalidation_level) and _is_invalidation_ok(sl_level):
        invalidation_level = sl_level

    return validation_level, invalidation_level


def _timeframe_candidates(timeframe: str) -> List[str]:
    raw = str(timeframe or "").strip().upper().replace(" ", "")
    if not raw:
        # Fallback sweep for cases where runtime context does not carry timeframe yet.
        return ["15", "15M", "5", "5M", "1H", "60", "4H", "240", "1D", "D", "1W", "W"]
    mapping = {
        "1": "1M",
        "1M": "1",
        "3": "3M",
        "3M": "3",
        "5": "5M",
        "5M": "5",
        "15": "15M",
        "15M": "15",
        "30": "30M",
        "30M": "30",
        "60": "1H",
        "1H": "60",
        "240": "4H",
        "4H": "240",
        "D": "1D",
        "1D": "D",
        "W": "1W",
        "1W": "W",
    }
    alt = mapping.get(raw)
    out = [raw]
    if alt and alt not in out:
        out.append(alt)
    # Add common canonical spellings so endpoint lookups are resilient.
    if raw.endswith("M") and raw[:-1].isdigit():
        compact = raw[:-1]
        if compact not in out:
            out.append(compact)
    elif raw.isdigit():
        expanded = f"{raw}M"
        if expanded not in out:
            out.append(expanded)
    # Last-resort scan candidates.
    for tf in ("15", "15M", "5", "5M", "1H", "60", "4H", "240", "1D", "D"):
        if tf not in out:
            out.append(tf)
    return out


async def verify_indicator_present(
    symbol: str,
    name: str,
    timeframe: str = "",
    timeout_sec: float = 6.0,
    poll_interval_sec: float = 0.25,
) -> Dict[str, Any]:
    """
    Verify that an indicator is present on the active TradingView chart.

    Intended flow:
    add_indicator -> verify_indicator_present -> get_active_indicators
    """
    tv_name = _INDICATOR_NAME_MAP.get(name, name)
    want_tokens = {_norm_indicator_token(tv_name), _norm_indicator_token(name)}
    want_tokens = {t for t in want_tokens if t}
    deadline = time.time() + max(0.0, float(timeout_sec))

    last_payload: Optional[Dict[str, Any]] = None
    tried: List[str] = []
    attempts = 0

    client = await get_http_client(timeout_sec=10.0)
    while True:
        attempts += 1
        for tf in _timeframe_candidates(timeframe):
            if tf not in tried:
                tried.append(tf)

            try:
                resp = await client.get(
                    f"{CONNECTORS_API}/tradingview/indicators",
                    params={"symbol": symbol, "timeframe": tf},
                )
            except Exception as exc:
                last_payload = {"error": f"Failed to query tradingview indicators: {exc}"}
                continue

            if resp.status_code == 404:
                last_payload = {"error": "No TradingView indicators cached yet"}
                continue
            try:
                resp.raise_for_status()
            except Exception as exc:
                last_payload = {"error": f"TradingView indicators HTTP error: {exc}", "http_status": resp.status_code}
                continue

            data = resp.json() if resp.content else {}
            last_payload = data if isinstance(data, dict) else {"raw": data}

            payload_data = (last_payload.get("data") or {}) if isinstance(last_payload, dict) else {}
            active = payload_data.get("active_indicators") or []
            indicators = payload_data.get("indicators") or {}

            active_tokens = {_norm_indicator_token(x) for x in (active if isinstance(active, list) else [])}
            key_tokens = {_norm_indicator_token(k) for k in (indicators.keys() if isinstance(indicators, dict) else [])}

            present = bool(want_tokens & active_tokens) or bool(want_tokens & key_tokens)
            if present:
                return {
                    "status": "ok",
                    "symbol": symbol,
                    "timeframe": tf,
                    "indicator": tv_name,
                    "present": True,
                    "attempts": attempts,
                    "active_indicators": active if isinstance(active, list) else [],
                }

        if time.time() >= deadline:
            return {
                "status": "error",
                "symbol": symbol,
                "timeframe": timeframe,
                "indicator": tv_name,
                "present": False,
                "attempts": attempts,
                "tried_timeframes": tried,
                "last_payload": last_payload,
                "error": f"Indicator '{tv_name}' not found on chart within {timeout_sec:.1f}s",
            }

        await asyncio.sleep(max(0.05, float(poll_interval_sec)))


async def list_supported_indicator_aliases() -> Dict[str, Any]:
    """
    Return supported indicator aliases and their TradingView canonical names.
    """
    aliases = sorted(_INDICATOR_NAME_MAP.keys())
    canonical = sorted(set(_INDICATOR_NAME_MAP.values()))
    return {
        "status": "ok",
        "aliases_count": len(aliases),
        "canonical_count": len(canonical),
        "aliases": aliases,
        "canonical_names": canonical,
        "alias_map": dict(sorted(_INDICATOR_NAME_MAP.items(), key=lambda item: item[0])),
    }


async def add_indicator(
    symbol: str,
    name: str,
    inputs: Dict[str, Any] = None,
    force_overlay: bool = False,
    write_txn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
    tv_name = _INDICATOR_NAME_MAP.get(name, name)
    return await send_tradingview_command(
        symbol=symbol,
        action="add_indicator",
        params={
            "name": tv_name,
            "inputs": inputs or {},
            # Force overlay is intentionally disabled to keep indicator panes clean.
            "forceOverlay": False,
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol, "indicator": tv_name},
    )


async def remove_indicator(
    symbol: str,
    name: str,
    write_txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    tv_name = _INDICATOR_NAME_MAP.get(name, name)
    return await send_tradingview_command(
        symbol=symbol,
        action="remove_indicator",
        params={
            "name": tv_name,
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol},
    )


async def clear_indicators(
    symbol: str,
    keep_volume: bool = False,
    write_txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await send_tradingview_command(
        symbol=symbol,
        action="clear_indicators",
        params={
            "keep_volume": bool(keep_volume),
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol},
    )


async def set_timeframe(symbol: str, timeframe: str, write_txn_id: Optional[str] = None) -> Dict[str, Any]:
    return await send_tradingview_command(
        symbol=symbol,
        action="set_timeframe",
        params={"timeframe": timeframe, "write_txn_id": write_txn_id},
        mode="write",
        expected_state={"symbol": symbol, "timeframe": timeframe},
    )


def _infer_target_source_from_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" in raw:
        base, quote = raw.split("-", 1)
        fiat = {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "MXN", "HKD"}
        if base in fiat and quote in fiat:
            return "ostium"
    rwa_bases = {
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
    base = raw.split("-", 1)[0]
    if base in rwa_bases:
        return "ostium"
    return "hyperliquid"


async def set_symbol(
    symbol: str,
    target_symbol: str,
    target_source: Optional[str] = None,
    write_txn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Switch the active TradingView chart to a different symbol or exchange.

    This tool can be used to:
    - Switch to a completely different symbol (e.g. BTC-USD -> ETH-USD)
    - Switch to the SAME symbol but on a DIFFERENT exchange/source
      (e.g. BTC-USD on Hyperliquid vs BTC-USD on Aster vs BTC-USD on dYdX)

    Args:
        symbol: The currently active chart symbol (used to route the command).
        target_symbol: The symbol to switch to (e.g. "BTC-USD", "ETH-USDT").
        target_source: The exchange/data source to use. Supported values:
            - "hyperliquid" → Hyperliquid perpetuals (default for most crypto)
            - "aster"       → Aster exchange
            - "aevo"        → Aevo options & perpetuals
            - "avantis"     → Avantis perpetuals
            - "dydx"        → dYdX perpetuals
            - "paradex"     → Paradex perpetuals
            - "orderly"     → Orderly Network
            - "vest"        → Vest exchange
            - "ostium"      → Ostium (RWA, forex pairs, stocks, commodities)
            If omitted, the exchange is auto-inferred from the symbol type.
            To switch the SAME symbol to a different exchange, always pass
            target_source explicitly (e.g. target_source="aster" for BTC on Aster).
        write_txn_id: Optional transaction ID for write verification.

    Examples:
        # Switch to ETH on Hyperliquid (auto-inferred)
        set_symbol("BTC-USD", "ETH-USD")

        # Switch BTC to Aster exchange (same symbol, different exchange)
        set_symbol("BTC-USD", "BTC-USD", target_source="aster")

        # Switch BTC to dYdX
        set_symbol("BTC-USD", "BTC-USD", target_source="dydx")

        # Switch BTC to Aevo
        set_symbol("BTC-USD", "BTC-USD", target_source="aevo")

        # Switch to a forex pair on Ostium
        set_symbol("BTC-USD", "EUR-USD", target_source="ostium")
    """
    resolved_source = str(target_source or "").strip().lower() or _infer_target_source_from_symbol(target_symbol)
    return await send_tradingview_command(
        symbol=symbol,
        action="set_symbol",
        params={
            "symbol": target_symbol,
            "target_source": resolved_source,
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": target_symbol},
    )


async def setup_trade(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    tp2: Optional[float] = None,
    tp3: Optional[float] = None,
    trailing_sl: Optional[float] = None,
    be: Optional[float] = None,
    liq: Optional[float] = None,
    gp: Optional[float] = None,
    gl: Optional[float] = None,
    validation: Optional[float] = None,
    invalidation: Optional[float] = None,
    validation_note: Optional[str] = None,
    invalidation_note: Optional[str] = None,
    write_txn_id: Optional[str] = None,
    tool_states: Optional[Dict[str, Any]] = None,
    amount_usd: Optional[float] = None,
    size_pct: Optional[float] = None,
    leverage: int = 1,
) -> Dict[str, Any]:
    normalized_side = str(side or "").lower()
    validation_level_raw = gp if gp is not None else validation
    invalidation_level_raw = gl if gl is not None else invalidation
    validation_level, invalidation_level = _normalize_trade_tripwire_levels(
        side=normalized_side,
        entry=entry,
        sl=sl,
        tp=tp,
        validation=validation_level_raw,
        invalidation=invalidation_level_raw,
    )
    expected: Dict[str, Any] = {"symbol": symbol, "side": normalized_side}
    if validation_level is not None:
        expected["validation"] = validation_level
    if invalidation_level is not None:
        expected["invalidation"] = invalidation_level
    chart_result = await send_tradingview_command(
        symbol=symbol,
        action="setup_trade",
        params={
            "side": normalized_side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "tp2": tp2,
            "tp3": tp3,
            "trailing_sl": trailing_sl,
            "be": be,
            "liq": liq,
            "gp": validation_level,
            "gl": invalidation_level,
            "validation": validation_level,
            "invalidation": invalidation_level,
            "validation_note": validation_note,
            "invalidation_note": invalidation_note,
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state=expected,
    )
    
    # NEW logic: Execute order alongside visualization if user expects setup_trade to also place order
    try:
        from agent.Tools.trade_execution import place_order
        
        # Use a sensible default size_pct if amount is not specified, so it actually places an order
        # as requested by the user. If they specify neither, we default to 25% balance.
        actual_size_pct = size_pct
        if amount_usd is None and size_pct is None:
            actual_size_pct = 0.25
            
        order_result = await place_order(
            symbol=symbol,
            side=side,
            amount_usd=amount_usd,
            size_pct=actual_size_pct,
            tool_states=tool_states,
            leverage=leverage,
            order_type="market",
            price=entry,
            tp=tp,
            sl=sl,
            validation=validation_level,
            invalidation=invalidation_level,
        )
        
        # If it returns a HITL proposal, bubble it up so the frontend catches it
        if order_result.get("status") == "proposal":
            order_result["visual_setup"] = chart_result
            return order_result
            
        return {
            "visual_setup": chart_result,
            "order_execution": order_result
        }
    except Exception as e:
        return {
            "visual_setup": chart_result,
            "order_execution_error": str(e)
        }


async def add_price_alert(symbol: str, price: float, message: str, write_txn_id: Optional[str] = None) -> Dict[str, Any]:
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    alert_id = f"alert_{int(price)}"
    return await send_tradingview_command(
        symbol=symbol,
        action="draw_shape",
        params={
            "type": "horizontal_line",
            "id": alert_id,
            "points": [{"time": now_ts, "price": price}],
            "text": f"ALERT: {message}",
            "style": {
                "color": "#FF9800",
                "linestyle": 1,
                "linewidth": 2,
                "text": f"{message}",
            },
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol, "drawing_id": alert_id},
    )


async def mark_trading_session(symbol: str, session: str, write_txn_id: Optional[str] = None) -> Dict[str, Any]:
    session = str(session or "").upper().strip()
    schedule = {
        "ASIA": {"start": 0, "end": 9, "color": "rgba(0, 0, 255, 0.1)", "text": "Tokyo"},
        "LONDON": {"start": 7, "end": 16, "color": "rgba(0, 255, 0, 0.1)", "text": "London"},
        "NEW_YORK": {"start": 13, "end": 22, "color": "rgba(255, 165, 0, 0.1)", "text": "NY"},
    }
    if session not in schedule:
        return {"error": f"Unknown session: {session}. Use ASIA, LONDON, or NEW_YORK."}

    cfg = schedule[session]
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    t_start = int((start_of_day + datetime.timedelta(hours=cfg["start"])).timestamp())
    t_end = int((start_of_day + datetime.timedelta(hours=cfg["end"])).timestamp())
    drawing_id = f"session_{session.lower()}"

    return await send_tradingview_command(
        symbol=symbol,
        action="draw_shape",
        params={
            "type": "rectangle",
            "id": drawing_id,
            "points": [{"time": t_start, "price": 1000000}, {"time": t_end, "price": 0}],
            "text": cfg["text"],
            "style": {"fillColor": cfg["color"], "color": cfg["color"], "filled": True},
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol, "drawing_id": drawing_id},
    )
