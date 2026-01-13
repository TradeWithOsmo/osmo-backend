"""Price history tracker for calculating 24h stats"""
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Optional, Deque
import logging

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
                "low_24h": None,
                "volume_24h": 0  # Ostium doesn't provide volume
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
            "volume_24h": 0,  # Not available from Ostium
            "data_points": len(self.prices)
        }


class PriceHistoryTracker:
    """Manage price history for all symbols"""
    
    def __init__(self):
        self.histories: Dict[str, PriceHistory] = {}
    
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
    
    def update_from_ostium_response(self, ostium_data: list):
        """Update all symbols from Ostium API response"""
        updated_count = 0
        
        if not isinstance(ostium_data, list):
            logger.warning(f"Expected list, got {type(ostium_data)}")
            return 0
        
        for item in ostium_data:
            try:
                # Handle both 'ticker' and 'symbol' field names
                symbol = item.get('ticker') or item.get('symbol') or item.get('name')
                price = item.get('price') or item.get('value')
                
                if not symbol or price is None:
                    continue
                
                price = float(price)
                
                # Normalize symbol (EURUSD → EUR-USD)
                if '-' not in symbol and len(symbol) == 6:
                    normalized_symbol = f"{symbol[:3]}-{symbol[3:]}"
                elif symbol.startswith('XAU') or symbol.startswith('XAG'):
                    # Handle metals
                    normalized_symbol = f"{symbol[:3]}-{symbol[3:]}"
                else:
                    normalized_symbol = symbol
                
                self.update_price(normalized_symbol, price)
                updated_count += 1
            except Exception as e:
                logger.error(f"Error updating price for item {item}: {e}")
                continue
        
        if updated_count > 0:
            logger.info(f"Updated price history for {updated_count} Ostium symbols")
        return updated_count
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get stats for all tracked symbols"""
        return {
            symbol: history.get_24h_stats()
            for symbol, history in self.histories.items()
        }
