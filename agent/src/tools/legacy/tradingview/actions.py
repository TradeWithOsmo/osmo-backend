"""
TradingView Action Tools

Write-mode chart actions with strict execution evidence support.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, Optional, List
import datetime

import httpx

from .command_client import send_tradingview_command
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


def _timeframe_candidates(timeframe: str) -> List[str]:
    raw = str(timeframe or "").strip().upper().replace(" ", "")
    if not raw:
        return ["1D"]
    mapping = {
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
    return out


async def verify_indicator_present(
    symbol: str,
    name: str,
    timeframe: str = "1D",
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

    async with httpx.AsyncClient(timeout=10.0) as client:
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
    expected: Dict[str, Any] = {"symbol": symbol, "side": normalized_side}
    if validation_level is not None:
        expected["validation"] = validation_level
    if invalidation_level is not None:
        expected["invalidation"] = invalidation_level
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
        expected_state=expected,
    )


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
