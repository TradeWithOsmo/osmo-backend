"""
TradingView Action Tools

Allows the agent to control the frontend TradingView chart.
"""

import httpx
from typing import Dict, Any, List, Optional
from backend.agent.Config.tools_config import DATA_SOURCES

CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")

async def add_indicator(symbol: str, name: str, inputs: Dict[str, Any] = None, force_overlay: bool = True) -> Dict[str, Any]:
    """
    Add an indicator to the TradingView chart for a specific symbol.
    
    Args:
        symbol: The trading symbol (e.g., "BTCUSD")
        name: Name of the indicator (must match TradingView PineScript name or built-in, e.g., "RSI", "MACD", "Moving Average")
        inputs: Dictionary of input values for the indicator (e.g., {"length": 14})
        force_overlay: Whether to force the indicator to overlay the main chart (True) or separate pane (False).
    """
    url = f"{CONNECTORS_API}/tradingview/commands"
    
    # Valid TradingView Indicators (106 Total)
    VALID_INDICATORS = [
        "52 Week High/Low", "Accelerator Oscillator", "Accumulation/Distribution", "Accumulative Swing Index",
        "Advance/Decline", "Arnaud Legoux Moving Average", "Aroon", "Average Directional Index", "Average Price",
        "Average True Range", "Awesome Oscillator", "Balance of Power", "Bollinger Bands", "Bollinger Bands %B",
        "Bollinger Bands Width", "Chaikin Money Flow", "Chaikin Oscillator", "Chaikin Volatility", "Chande Kroll Stop",
        "Chande Momentum Oscillator", "Chop Zone", "Choppiness Index", "Commodity Channel Index", "Connors RSI",
        "Coppock Curve", "Correlation - Log", "Correlation Coefficient", "Detrended Price Oscillator", "Directional Movement",
        "Donchian Channels", "Double EMA", "Ease Of Movement", "Elder's Force Index", "EMA Cross", "Envelopes",
        "Fisher Transform", "Guppy Multiple Moving Average", "Historical Volatility", "Hull Moving Average", "Ichimoku Cloud",
        "Keltner Channels", "Klinger Oscillator", "Know Sure Thing", "Least Squares Moving Average", "Linear Regression Curve",
        "Linear Regression Slope", "MA Cross", "MA with EMA Cross", "MACD", "Majority Rule", "Mass Index",
        "McGinley Dynamic", "Median Price", "Momentum", "Money Flow Index", "Moving Average", "Moving Average Adaptive",
        "Moving Average Channel", "Moving Average Double", "Moving Average Exponential", "Moving Average Hamming",
        "Moving Average Multiple", "Moving Average Triple", "Moving Average Weighted", "Net Volume", "On Balance Volume",
        "Parabolic SAR", "Pivot Points Standard", "Price Channel", "Price Oscillator", "Price Volume Trend", "Rate Of Change",
        "Ratio", "Relative Strength Index", "Relative Vigor Index", "Relative Volatility Index", "SMI Ergodic Indicator/Oscillator",
        "Smoothed Moving Average", "Spread", "Standard Deviation", "Standard Error", "Standard Error Bands", "Stochastic",
        "Stochastic RSI", "SuperTrend", "Trend Strength Index", "Triple EMA", "TRIX", "True Strength Index",
        "Typical Price", "Ultimate Oscillator", "Volatility Close-to-Close", "Volatility Index", "Volatility O-H-L-C",
        "Volatility Zero Trend Close-to-Close", "Volume", "Volume Oscillator", "Volume Profile Fixed Range",
        "Volume Profile Visible Range", "Vortex Indicator", "VWAP", "VWMA", "Williams %R", "Williams Alligator",
        "Williams Fractal", "Zig Zag"
    ]

    # Map common names to TradingView internal names/IDs if possible
    # This is a heuristic mapping; complex cases might need specific IDs.
    name_map = {
        # Momentum
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
        
        # Trend
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
        
        # Volatility
        "ATR": "Average True Range",
        "Keltner": "Keltner Channels",
        "Donchian": "Donchian Channels",
        "HV": "Historical Volatility",
        
        # Volume
        "OBV": "On Balance Volume",
        "VWAP": "VWAP",
        "VPVR": "Volume Profile Visible Range",
        "VPFR": "Volume Profile Fixed Range",
        "Volume": "Volume",
        "CMF": "Chaikin Money Flow",
        "EOM": "Ease Of Movement"
    }
    
    # Use mapped name if available, otherwise pass through
    tv_name = name_map.get(name, name)

    command = {
        "symbol": symbol,
        "action": "add_indicator",
        "params": {
            "name": tv_name,
            "inputs": inputs or {},
            "forceOverlay": force_overlay
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=command)
            resp.raise_for_status()
            return {"status": "success", "info": f"Indicator '{name}' added to {symbol} chart queue."}
        except Exception as e:
            return {"error": f"Failed to add indicator: {str(e)}"}

async def set_timeframe(symbol: str, timeframe: str) -> Dict[str, Any]:
    """
    Change the timeframe of the TradingView chart.
    
    Args:
        symbol: The trading symbol (e.g., "BTCUSD")
        timeframe: The target timeframe (e.g., "1m", "5m", "1h", "4h", "1D")
    """
    url = f"{CONNECTORS_API}/tradingview/commands"
    
    command = {
        "symbol": symbol,
        "action": "set_timeframe",
        "params": {
            "timeframe": timeframe
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=command)
            resp.raise_for_status()
            return {"status": "success", "info": f"Timeframe set to {timeframe} for {symbol}."}
        except Exception as e:
            return {"error": f"Failed to set timeframe: {str(e)}"}

async def set_symbol(symbol: str, target_symbol: str) -> Dict[str, Any]:
    """
    Change the symbol/ticker of the chart.
    
    Args:
        symbol: Current symbol identifier (not used for targeting, but for consistency).
        target_symbol: The new symbol to load (e.g., "ETHUSDT", "NASDAQ:AAPL").
    """
    url = f"{CONNECTORS_API}/tradingview/commands"
    
    command = {
        "symbol": symbol,
        "action": "set_symbol",
        "params": {
            "symbol": target_symbol
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=command)
            resp.raise_for_status()
            return {"status": "success", "info": f"Chart switched to {target_symbol}."}
        except Exception as e:
            return {"error": f"Failed to set symbol: {str(e)}"}

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
    gl: Optional[float] = None
) -> Dict[str, Any]:
    """
    Visually setup a trade on the chart using Native Order Lines.
    
    Args:
        symbol: The trading symbol.
        side: "long" or "short"
        entry: Entry price.
        sl: Stop Loss price.
        tp: Take Profit 1 price.
        tp2: (Optional) Take Profit 2 price.
        tp3: (Optional) Take Profit 3 price.
        trailing_sl: (Optional) Trailing Stop price.
        be: (Optional) Break Even price.
        liq: (Optional) Liquidation price.
        gp: (Optional) Generate Profit Decision (AI Tripwire).
        gl: (Optional) Generate Loss Decision (AI Tripwire).
    """
    enhanced_command = {
        "symbol": symbol,
        "action": "setup_trade", # Special action for the handler
        "params": {
            "side": side.lower(),
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "tp2": tp2,
            "tp3": tp3,
            "trailing_sl": trailing_sl,
            "be": be,
            "liq": liq,
            "gp": gp,
            "gl": gl
        }
    }
    
    url = f"{CONNECTORS_API}/tradingview/commands"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=enhanced_command)
            resp.raise_for_status()
            return {"status": "success", "info": f"Trade setup ({side}) visualized on chart."}
        except Exception as e:
            return {"error": f"Failed to setup trade: {str(e)}"}

async def add_price_alert(symbol: str, price: float, message: str) -> Dict[str, Any]:
    """
    Create a Price Alert.
    1. Visualizes it on the chart (Dashed Orange Line).
    2. Registers it in the system for monitoring.
    """
    # 1. Visualization Command
    visual_cmd = {
        "symbol": symbol,
        "action": "draw_shape",
        "params": {
            "type": "horizontal_line",
            "id": f"alert_{int(price)}",
            "points": [{"price": price}],
            "text": f"🔔 ALERT: {message}",
            "style": {
                "color": "#FF9800",
                "linestyle": 1,
                "linewidth": 2,
                "text": f"🔔 {message}"
            }
        }
    }

    # 2. System Registration (for log)
    print(f"Server: Registered Alert for {symbol} @ {price} | Msg: {message}")

    url = f"{CONNECTORS_API}/tradingview/commands"
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=visual_cmd)
            return {"status": "success", "info": f"Alert set at {price}: {message}"}
        except Exception as e:
            return {"error": f"Failed to set alert: {str(e)}"}

async def mark_trading_session(symbol: str, session: str) -> Dict[str, Any]:
    """
    Highlight a trading session on the current day's chart.
    Sessions: 'ASIA', 'LONDON', 'NEW_YORK'.
    Assumes chart is on UTC or aligns with UTC calculations.
    """
    # Local import is fine to avoid top-level clutter if preferred, or move to top.
    import datetime 
    
    session = session.upper()
    
    SCHEDULE = {
        "ASIA": {"start": 0, "end": 9, "color": "rgba(0, 0, 255, 0.1)", "text": "Tokyo"},
        "LONDON": {"start": 7, "end": 16, "color": "rgba(0, 255, 0, 0.1)", "text": "London"},
        "NEW_YORK": {"start": 13, "end": 22, "color": "rgba(255, 165, 0, 0.1)", "text": "NY"},
    }

    if session not in SCHEDULE:
        return {"error": f"Unknown session: {session}. Use ASIA, LONDON, or NEW_YORK."}
    
    cfg = SCHEDULE[session]
    
    # Calculate timestamps for "Today"
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    
    t_start = int((start_of_day + datetime.timedelta(hours=cfg["start"])).timestamp())
    t_end = int((start_of_day + datetime.timedelta(hours=cfg["end"])).timestamp())
    
    cmd = {
        "symbol": symbol,
        "action": "draw_shape",
        "params": {
            "type": "rectangle",
            "id": f"session_{session.lower()}",
            "points": [
                {"time": t_start, "price": 1000000}, # Sky High
                {"time": t_end, "price": 0}        # Ground Zero (or -1000)
            ],
            "text": cfg["text"],
            "style": {
                "fillColor": cfg["color"],
                "color": cfg["color"],
                "filled": True
            }
        }
    }
    
    url = f"{CONNECTORS_API}/tradingview/commands"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=cmd)
            return {"status": "success", "info": f"Marked {session} session."}
        except Exception as e:
            return {"error": f"Failed to mark session: {str(e)}"}
