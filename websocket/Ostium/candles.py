"""In-memory OHLC candle generator for Ostium"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)

class Candle:
    def __init__(self, timestamp: int, open_price: float, high: float, low: float, close: float):
        self.timestamp = timestamp  # Milliseconds
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.interval = "1m"  # Default to 1 minute
        self.symbol = None # Added for persistence context

    def update(self, price: float):
        """Update candle with new price"""
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price

    def to_dict(self):
        return {
            "t": self.timestamp,
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "i": self.interval
        }

class CandleGenerator:
    """Generates 1-minute candles from real-time price updates"""
    
    def __init__(self, max_history: int = 1440, queue: asyncio.Queue = None):
        self.candles: Dict[str, List[Candle]] = {} # symbol -> list of candles
        self.current_candles: Dict[str, Candle] = {} # symbol -> current active candle
        self.max_history = max_history
        self.queue = queue

    def update_price(self, symbol: str, price: float, timestamp: int = None):
        """Process new price update"""
        if timestamp is None:
            timestamp = int(datetime.now().timestamp() * 1000)
            
        # Calculate current minute start timestamp
        # Round down to nearest minute
        minute_ts = (timestamp // 60000) * 60000
        
        # Check if we have a current candle for this symbol
        if symbol not in self.current_candles:
            # Start new candle
            self.current_candles[symbol] = Candle(minute_ts, price, price, price, price)
            self.current_candles[symbol].symbol = symbol # Store symbol for persistence
            if symbol not in self.candles:
                self.candles[symbol] = []
        else:
            current = self.current_candles[symbol]
            
            if current.timestamp == minute_ts:
                # Still in same minute, update current
                current.update(price)
            else:
                # New minute started
                # 1. Archive old candle
                if symbol not in self.candles:
                    self.candles[symbol] = []
                self.candles[symbol].append(current)
                
                # Push to persistence queue if available
                if self.queue:
                    try:
                        self.queue.put_nowait(current)
                    except Exception as e:
                        logger.error(f"Failed to queue candle for persistence: {e}")
                
                # Maintain max history
                if len(self.candles[symbol]) > self.max_history:
                    self.candles[symbol].pop(0)
                
                # 2. Start new candle
                self.current_candles[symbol] = Candle(minute_ts, price, price, price, price)
                self.current_candles[symbol].symbol = symbol

    def get_candles(self, symbol: str, limit: int = 100) -> List[dict]:
        """Get historical candles + current unfinished candle"""
        if symbol not in self.candles and symbol not in self.current_candles:
            return []
            
        result = []
        
        # Add history
        if symbol in self.candles:
            result.extend([c.to_dict() for c in self.candles[symbol]])
            
        # Add current active candle (real-time)
        if symbol in self.current_candles:
            result.append(self.current_candles[symbol].to_dict())
            
        # Return last N candles
        return result[-limit:]
