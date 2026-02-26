"""Background polling service for Vest Exchange"""
import asyncio
import logging
from typing import Callable, Optional, List, Dict, Any
from datetime import datetime
from .api_client import VestAPIClient

logger = logging.getLogger(__name__)


class VestPoller:
    """Polls Vest Exchange REST API at a fixed interval."""

    def __init__(self, api_client: VestAPIClient, poll_interval: int = 5, callback: Optional[Callable] = None):
        self.api_client = api_client
        self.poll_interval = poll_interval
        self.callback = callback
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.last_poll_time: Optional[datetime] = None
        self.poll_count = 0
        self._last_prices: List[Dict[str, Any]] = []

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.task = asyncio.create_task(self._poll_loop())
        logger.info(f"[Vest] Poller started (interval: {self.poll_interval}s)")

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("[Vest] Poller stopped")

    async def _poll_loop(self):
        while self.is_running:
            try:
                prices = await self.api_client.get_latest_prices()
                if prices:
                    self._last_prices = prices
                    self.last_poll_time = datetime.now()
                    self.poll_count += 1
                    if self.callback:
                        await self.callback(prices)
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Vest] Poll error: {e}")
                await asyncio.sleep(self.poll_interval * 2)

    def get_last_prices(self) -> List[Dict[str, Any]]:
        return self._last_prices

    def get_status(self) -> dict:
        return {
            "running": self.is_running,
            "poll_interval": self.poll_interval,
            "poll_count": self.poll_count,
            "last_poll_time": self.last_poll_time.isoformat() if self.last_poll_time else None,
        }
