"""Background polling service for Ostium API"""
import asyncio
import logging
from typing import Callable, Optional
from datetime import datetime

from .api_client import OstiumAPIClient

logger = logging.getLogger(__name__)


class OstiumPoller:
    """Background service that polls Ostium API at configured intervals"""
    
    def __init__(
        self,
        api_client: OstiumAPIClient,
        poll_interval: int = 2,  # seconds
        callback: Optional[Callable] = None
    ):
        self.api_client = api_client
        self.poll_interval = poll_interval
        self.callback = callback
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.last_poll_time: Optional[datetime] = None
        self.poll_count = 0
    
    async def start(self):
        """Start the polling service"""
        if self.is_running:
            logger.warning("Ostium poller already running")
            return
        
        self.is_running = True
        self.task = asyncio.create_task(self._poll_loop())
        logger.info(f"✅ Ostium poller started (interval: {self.poll_interval}s)")
    
    async def stop(self):
        """Stop the polling service"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Ostium poller stopped")
    
    async def _poll_loop(self):
        """Main polling loop"""
        while self.is_running:
            try:
                # Fetch latest prices from Ostium
                prices = await self.api_client.get_latest_prices()
                
                if prices and self.callback:
                    await self.callback(prices)
                    self.last_poll_time = datetime.now()
                    self.poll_count += 1
                
                # Wait for next poll interval
                await asyncio.sleep(self.poll_interval)
            
            except asyncio.CancelledError:
                break
            
            except Exception as e:
                logger.error(f"Error in Ostium poll loop: {e}")
                # Increase wait time on error to prevent rapid retries
                await asyncio.sleep(self.poll_interval * 2)
    
    def get_status(self) -> dict:
        """Get poller status"""
        return {
            "running": self.is_running,
            "poll_interval": self.poll_interval,
            "poll_count": self.poll_count,
            "last_poll_time": self.last_poll_time.isoformat() if self.last_poll_time else None
        }
