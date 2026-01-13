"""Ostium API client with circuit breaker and retry logic"""
import httpx
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker to prevent excessive API calls during failures"""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # seconds
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False
    
    def record_success(self):
        """Record successful API call"""
        self.failures = 0
        self.is_open = False
    
    def record_failure(self):
        """Record failed API call"""
        self.failures += 1
        self.last_failure_time = datetime.now()
        
        if self.failures >= self.failure_threshold:
            self.is_open = True
            logger.warning(f"⚠️ Circuit breaker OPEN after {self.failures} failures")
    
    def can_attempt(self) -> bool:
        """Check if we can attempt an API call"""
        if not self.is_open:
            return True
        
        # Check if timeout has passed
        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.timeout:
                logger.info("🔄 Circuit breaker attempting half-open state")
                self.is_open = False
                self.failures = 0
                return True
        
        return False


class OstiumAPIClient:
    """HTTP client for Ostium API with circuit breaker and retry logic"""
    
    def __init__(self, api_url: str = "https://metadata-backend.ostium.io"):
        self.api_url = api_url
        self.client = httpx.AsyncClient(timeout=10.0, verify=False)
        self.circuit_breaker = CircuitBreaker()
        self.last_successful_fetch: Optional[datetime] = None
    
    async def get_latest_prices(self) -> Optional[Dict[str, Any]]:
        """
        Get latest prices for all Ostium feeds
        
        Returns:
            {"EURUSD": {"price": "1.0950", "timestamp": 1705180000000}, ...}
        """
        if not self.circuit_breaker.can_attempt():
            logger.warning("Circuit breaker is OPEN, skipping API call")
            return None
        
        url = f"{self.api_url}/PricePublish/latest-prices"
        
        try:
            response = await self.client.get(url, headers={"Content-Type": "application/json"})
            
            if response.status_code == 200:
                self.circuit_breaker.record_success()
                self.last_successful_fetch = datetime.now()
                return response.json()
            
            elif response.status_code == 429:
                logger.warning("⚠️ Rate limited by Ostium API (429)")
                self.circuit_breaker.record_failure()
                return None
            
            else:
                logger.error(f"Ostium API error {response.status_code}: {response.text}")
                self.circuit_breaker.record_failure()
                return None
        
        except httpx.TimeoutException:
            logger.error("Ostium API request timed out")
            self.circuit_breaker.record_failure()
            return None
        
        except Exception as e:
            logger.error(f"Ostium API request failed: {e}")
            self.circuit_breaker.record_failure()
            return None
    
    async def get_price_for_asset(self, asset: str) -> Optional[Dict[str, Any]]:
        """
        Get latest price for a specific asset
        
        Args:
            asset: Asset symbol (e.g., "EURUSD")
        
        Returns:
            Price data dictionary
        """
        if not self.circuit_breaker.can_attempt():
            return None
        
        url = f"{self.api_url}/PricePublish/latest-price?asset={asset}"
        
        try:
            response = await self.client.get(url, headers={"Content-Type": "application/json"})
            
            if response.status_code == 200:
                self.circuit_breaker.record_success()
                return response.json()
            else:
                self.circuit_breaker.record_failure()
                return None
        
        except Exception as e:
            logger.error(f"Failed to fetch {asset} price: {e}")
            self.circuit_breaker.record_failure()
            return None
    
    async def get_trading_hours(self, asset: str) -> Optional[Dict[str, Any]]:
        """Get trading hours for an RWA asset"""
        url = f"{self.api_url}/trading-hours/asset-schedule?asset={asset}"
        
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch trading hours for {asset}: {e}")
        
        return None
    
    def get_status(self) -> dict:
        """Get client status"""
        return {
            "circuit_breaker_open": self.circuit_breaker.is_open,
            "failures": self.circuit_breaker.failures,
            "last_successful_fetch": self.last_successful_fetch.isoformat() if self.last_successful_fetch else None
        }
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
