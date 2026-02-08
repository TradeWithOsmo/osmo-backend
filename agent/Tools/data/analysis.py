"""
Technical Analysis Tool

Wraps the Analysis Engine API to provide mathematical pattern detection and indicators.
"""

import httpx
from typing import Dict, Any, List, Optional
try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES

# Base URL
ANALYSIS_API = DATA_SOURCES.get("analysis", "http://localhost:8000/api/analysis")
FIAT_CODES = {"USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD", "MXN", "HKD"}


def _is_fiat_cross_symbol(symbol: str) -> bool:
    raw = (symbol or "").strip().upper().replace("/", "-").replace("_", "-")
    if "-" not in raw:
        return False
    base, quote = raw.split("-", 1)
    return base in FIAT_CODES and quote in FIAT_CODES

async def get_technical_analysis(symbol: str, timeframe: str = "1D", asset_type: str = "crypto") -> Dict[str, Any]:
    """
    Get full technical analysis report.
    Returns calculated indicators (RSI, MACD) and detected patterns (Doji, Engulfing).
    """
    if str(asset_type or "").strip().lower() == "rwa" and _is_fiat_cross_symbol(symbol):
        return {
            "error": (
                f"Technical analysis unsupported for fiat-RWA symbol '{symbol}'. "
                "Use price/action + macro/news context instead."
            )
        }

    url = f"{ANALYSIS_API}/technical/{symbol}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"timeframe": timeframe, "asset_type": asset_type})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}

async def get_patterns(symbol: str, timeframe: str = "1D", asset_type: str = "crypto") -> List[str]:
    """
    Get only the detected candlestick patterns.
    """
    data = await get_technical_analysis(symbol, timeframe, asset_type=asset_type)
    if "error" in data: return []
    return data.get("patterns", [])

async def get_indicators(symbol: str, timeframe: str = "1D", asset_type: str = "crypto") -> Dict[str, float]:
    """
    Get only the calculated indicators (RSI, MACD).
    """
    data = await get_technical_analysis(symbol, timeframe, asset_type=asset_type)
    if "error" in data: return {}
    return data.get("indicators", {})

async def get_technical_summary(symbol: str, timeframe: str = "1D", asset_type: str = "crypto") -> str:
    """
    Get a string summary of the technical status.
    """
    data = await get_technical_analysis(symbol, timeframe, asset_type=asset_type)
    if "error" in data: return f"Could not analyze {symbol}."
    
    price = data.get("price", 0)
    patterns = data.get("patterns", [])
    indicators = data.get("indicators", {})
    rsi = indicators.get("RSI_14", "N/A")
    
    summary = f"Analysis for {symbol} (${price}):\n"
    summary += f"- RSI: {rsi}\n"
    summary += f"- Patterns: {', '.join(patterns) if patterns else 'None Detected'}"
    
    return summary
