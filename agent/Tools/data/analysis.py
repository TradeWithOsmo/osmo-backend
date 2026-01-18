"""
Technical Analysis Tool

Wraps the Analysis Engine API to provide mathematical pattern detection and indicators.
"""

import httpx
from typing import Dict, Any, List, Optional
from backend.agent.Config.tools_config import DATA_SOURCES

# Base URL
ANALYSIS_API = DATA_SOURCES.get("analysis", "http://localhost:8000/api/analysis")

async def get_technical_analysis(symbol: str, timeframe: str = "1D") -> Dict[str, Any]:
    """
    Get full technical analysis report.
    Returns calculated indicators (RSI, MACD) and detected patterns (Doji, Engulfing).
    """
    url = f"{ANALYSIS_API}/technical/{symbol}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"timeframe": timeframe})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}

async def get_patterns(symbol: str, timeframe: str = "1D") -> List[str]:
    """
    Get only the detected candlestick patterns.
    """
    data = await get_technical_analysis(symbol, timeframe)
    if "error" in data: return []
    return data.get("patterns", [])

async def get_indicators(symbol: str, timeframe: str = "1D") -> Dict[str, float]:
    """
    Get only the calculated indicators (RSI, MACD).
    """
    data = await get_technical_analysis(symbol, timeframe)
    if "error" in data: return {}
    return data.get("indicators", {})

async def get_technical_summary(symbol: str, timeframe: str = "1D") -> str:
    """
    Get a string summary of the technical status.
    """
    data = await get_technical_analysis(symbol, timeframe)
    if "error" in data: return f"Could not analyze {symbol}."
    
    price = data.get("price", 0)
    patterns = data.get("patterns", [])
    indicators = data.get("indicators", {})
    rsi = indicators.get("RSI_14", "N/A")
    
    summary = f"Analysis for {symbol} (${price}):\n"
    summary += f"- RSI: {rsi}\n"
    summary += f"- Patterns: {', '.join(patterns) if patterns else 'None Detected'}"
    
    return summary
