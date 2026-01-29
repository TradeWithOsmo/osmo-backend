
"""Price history tracker for calculating 24h stats"""
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional, Deque
import logging
import os

logger = logging.getLogger(__name__)

class PriceHistory:
    """Track price history for a single symbol"""
    
    def __init__(self, symbol: str, max_age_hours: int = 24):
        self.symbol = symbol
        self.max_age_hours = max_age_hours
        self.prices: Deque[tuple[float, datetime]] = deque()  # (price, timestamp)
    
    def add_price(self, price: float, timestamp: Optional[datetime] = None):
        """Add new price to history"""
        if timestamp is None:
            timestamp = datetime.now()
        
        self.prices.append((price, timestamp))
        self._cleanup_old_prices()
    
    def _cleanup_old_prices(self):
        """Remove prices older than max_age"""
        cutoff = datetime.now() - timedelta(hours=self.max_age_hours)
        while self.prices and self.prices[0][1] < cutoff:
            self.prices.popleft()
    
    def get_24h_stats(self) -> Dict[str, any]:
        """Calculate 24h statistics"""
        if not self.prices:
            return {
                "change_24h": 0,
                "change_percent_24h": 0,
                "high_24h": None,
                "low_24h": None
            }
        
        current_price = self.prices[-1][0]
        prices_only = [p for p, _ in self.prices]
        
        # Get 24h ago price (oldest in deque after cleanup)
        price_24h_ago = self.prices[0][0]
        
        # Calculate stats
        change_24h = current_price - price_24h_ago
        change_percent_24h = (change_24h / price_24h_ago * 100) if price_24h_ago > 0 else 0
        high_24h = max(prices_only)
        low_24h = min(prices_only)
        
        return {
            "change_24h": round(change_24h, 6),
            "change_percent_24h": round(change_percent_24h, 2),
            "high_24h": round(high_24h, 6),
            "low_24h": round(low_24h, 6),
            "data_points": len(self.prices)
        }


class PriceHistoryTracker:
    """Manage price history for all symbols"""
    
    def __init__(self, name: str = "generic"):
        self.histories: Dict[str, PriceHistory] = {}
        self.name = name
    
    def update_price(self, symbol: str, price: float, timestamp: Optional[datetime] = None):
        """Update price for a symbol"""
        if symbol not in self.histories:
            self.histories[symbol] = PriceHistory(symbol)
        
        self.histories[symbol].add_price(price, timestamp)
    
    def get_stats(self, symbol: str) -> Optional[Dict[str, any]]:
        """Get 24h stats for a symbol"""
        if symbol not in self.histories:
            return None
        
        return self.histories[symbol].get_24h_stats()
    
    def save_to_disk(self, filepath: str):
        """Save price history to disk"""
        try:
            data = {}
            for symbol, history in self.histories.items():
                prices_list = [(p, t.isoformat()) for p, t in history.prices]
                data[symbol] = prices_list
            
            import json
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(data, f)
            logger.info(f"[{self.name}] Saved price history for {len(data)} symbols")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save price history: {e}")

    def load_from_disk(self, filepath: str):
        """Load price history from disk"""
        import json
        if not os.path.exists(filepath):
            return
            
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            count = 0
            for symbol, prices_list in data.items():
                if symbol not in self.histories:
                    self.histories[symbol] = PriceHistory(symbol)
                
                history = self.histories[symbol]
                history.prices.clear()
                for p, t_str in prices_list:
                    t = datetime.fromisoformat(t_str)
                    if t > datetime.now() - timedelta(hours=24):
                        history.prices.append((p, t))
                count += 1
            
            logger.info(f"[{self.name}] Loaded price history for {count} symbols")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to load price history: {e}")
