"""
TradingView Action Tools

Write-mode chart actions with strict execution evidence support.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import datetime

from .command_client import send_tradingview_command


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
    force_overlay: bool = True,
    write_txn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
    tv_name = _INDICATOR_NAME_MAP.get(name, name)
    return await send_tradingview_command(
        symbol=symbol,
        action="add_indicator",
        params={
            "name": tv_name,
            "inputs": inputs or {},
            "forceOverlay": force_overlay,
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
) -> Dict[str, Any]:
    normalized_side = str(side or "").lower()
    validation_level = gp if gp is not None else validation
    invalidation_level = gl if gl is not None else invalidation
    return await send_tradingview_command(
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
            # Keep legacy gp/gl while exposing clearer validation/invalidation semantics.
            "gp": validation_level,
            "gl": invalidation_level,
            "validation": validation_level,
            "invalidation": invalidation_level,
            "validation_note": validation_note,
            "invalidation_note": invalidation_note,
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol, "side": normalized_side},
    )


async def add_price_alert(symbol: str, price: float, message: str, write_txn_id: Optional[str] = None) -> Dict[str, Any]:
    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    return await send_tradingview_command(
        symbol=symbol,
        action="draw_shape",
        params={
            "type": "horizontal_line",
            "id": f"alert_{int(price)}",
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
        expected_state={"symbol": symbol},
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

    return await send_tradingview_command(
        symbol=symbol,
        action="draw_shape",
        params={
            "type": "rectangle",
            "id": f"session_{session.lower()}",
            "points": [{"time": t_start, "price": 1000000}, {"time": t_end, "price": 0}],
            "text": cfg["text"],
            "style": {"fillColor": cfg["color"], "color": cfg["color"], "filled": True},
            "write_txn_id": write_txn_id,
        },
        mode="write",
        expected_state={"symbol": symbol},
    )
