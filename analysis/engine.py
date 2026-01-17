import pandas as pd
import pandas_ta as ta  # type: ignore
from typing import Dict, List, Any, Optional

class TechnicalAnalysisEngine:
    """
    Algorithmic Analysis Engine using pandas-ta.
    Processes raw OHLCV data to detect patterns and calculate indicators.
    """

    def __init__(self):
        pass

    def analyze_ticker(self, symbol: str, timeframe: str, ohlcv_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze a ticker based on provided OHLCV data.
        
        Args:
            symbol: Ticker symbol (e.g., "BTC")
            timeframe: Data timeframe (e.g., "1D")
            ohlcv_data: List of dicts [{"timestamp": 123, "open": 42000, ...}, ...]
            
        Returns:
            Dict containing calculated indicators and detected patterns.
        """
        if not ohlcv_data or len(ohlcv_data) < 14:
            return {
                "symbol": symbol,
                "error": "Insufficient data for analysis (need 14+ candles)"
            }

        # 1. Convert to DataFrame
        df = pd.DataFrame(ohlcv_data)
        
        # Deduplicate columns (in case input has dupes)
        df = df.loc[:, ~df.columns.duplicated()]
        
        # Ensure correct types
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])

        # 2. Calculate Indicators (RSI, basic MACD)
        # RSI 14
        df['RSI_14'] = df.ta.rsi(length=14)
        
        # MACD (12, 26, 9)
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        if macd is not None:
             df = pd.concat([df, macd], axis=1)

        # 3. Pattern Recognition (CDL Patterns)
        # Using pandas-ta cd_pattern (requires standard TA-Lib or ta-lib implementation)
        # Since standard TA-Lib binaries are hard to install, we use pandas-ta's internal fallback or simple logic.
        
        # 3. Pattern Recognition (Pure Python - No TA-Lib required)
        detected_patterns = []
        try:
            # Helper for safe access
            def safe_get(col, idx):
                if col not in df.columns: return 0.0
                val = df[col].iloc[idx]
                return float(val.iloc[0]) if isinstance(val, pd.Series) else float(val)

            # Get last 3 candles for complex patterns
            c0_op, c0_cl = safe_get('open', -1), safe_get('close', -1) # Current
            c0_hi, c0_lo = safe_get('high', -1), safe_get('low', -1)
            
            c1_op, c1_cl = safe_get('open', -2), safe_get('close', -2) # Prev
            c1_hi, c1_lo = safe_get('high', -2), safe_get('low', -2)

            # Properties
            body = abs(c0_cl - c0_op)
            rng = c0_hi - c0_lo
            avg_body = (abs(c0_cl - c0_op) + abs(c1_cl - c1_op)) / 2.0
            
            # 1. Doji (Body < 10% of range)
            if rng > 0 and (body / rng) < 0.1:
                detected_patterns.append("Doji")
                if c0_op < c0_lo + (rng * 0.1): detected_patterns.append("Dragonfly Doji")
                if c0_op > c0_hi - (rng * 0.1): detected_patterns.append("Gravestone Doji")

            # 2. Engulfing
            # Bullish: Prev Red, Curr Green, Curr Body > Prev Body, Curr Low < Prev Low
            if (c1_cl < c1_op) and (c0_cl > c0_op): # Red then Green
                if (c0_cl >= c1_op) and (c0_op <= c1_cl): # Engulfs body
                     detected_patterns.append("Bullish Engulfing")
            
            # Bearish: Prev Green, Curr Red
            if (c1_cl > c1_op) and (c0_cl < c0_op): # Green then Red
                if (c0_cl <= c1_op) and (c0_op >= c1_cl): # Engulfs
                    detected_patterns.append("Bearish Engulfing")

            # 3. Hammer / Shooting Star
            # Hammer: Small body, long lower wick, small/no upper wick, Downtrend (simplified)
            lower_wick = min(c0_op, c0_cl) - c0_lo
            upper_wick = c0_hi - max(c0_op, c0_cl)
            if rng > 0:
                is_small_body = (body / rng) < 0.3
                is_long_lower = (lower_wick / rng) > 0.6
                is_long_upper = (upper_wick / rng) > 0.6
                
                if is_small_body and is_long_lower and (upper_wick / rng) < 0.1:
                    detected_patterns.append("Hammer (Bullish)")
                if is_small_body and is_long_upper and (lower_wick / rng) < 0.1:
                    detected_patterns.append("Shooting Star (Bearish)")

            # 4. Marubozu (Full body, no wicks)
            if rng > 0 and (body / rng) > 0.9:
                if c0_cl > c0_op: detected_patterns.append("Bullish Marubozu")
                else: detected_patterns.append("Bearish Marubozu")

        except Exception as e:
            print(f"Pattern detection error: {e}")

        # Prepare Result - Defensive Extraction
        try:
            # Extract timestamp safely
            ts = 0
            if 'timestamp' in df.columns:
                val = df['timestamp'].iloc[-1]
                # If it's a series (duplicate cols), take first
                if isinstance(val, pd.Series):
                    val = val.iloc[0]
                ts = int(val)
            
            # Helper to safely get float
            def get_val(col):
                if col not in df.columns: return None
                val = df[col].iloc[-1]
                if isinstance(val, pd.Series):
                    val = val.iloc[0]
                if pd.isna(val): return None
                return float(val)

            result = {
                "symbol": symbol,
                "timeframe": timeframe,
                "price": get_val('close') or 0.0,
                "timestamp": ts,
                "indicators": {
                    "RSI_14": get_val('RSI_14'),
                    "MACD": get_val('MACD_12_26_9'),
                    "MACD_Signal": get_val('MACDs_12_26_9'),
                },
                "patterns": detected_patterns
            }
            return result
            
        except Exception as e:
            print(f"Result construction error: {e}")
            return {
                "symbol": symbol,
                "error": f"Analysis failed: {str(e)}"
            }
