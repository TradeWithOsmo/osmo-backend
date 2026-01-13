import asyncio
import logging
from typing import List
from sqlalchemy.future import select
from database.connection import AsyncSessionLocal
from database.models import Candle as CandleModel
from .candles import Candle

logger = logging.getLogger(__name__)

class CandlePersister:
    """Background service to persist candles to database"""
    
    def __init__(self, queue: asyncio.Queue, batch_size: int = 10, flush_interval: int = 5):
        self.queue = queue
        self.batch_size = batch_size
        self.flush_interval = flush_interval # Seconds
        self.running = False
        self._task = None

    async def start(self):
        """Start the persistence loop"""
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("💾 Candle persister started")

    async def stop(self):
        """Stop the persistence loop"""
        self.running = False
        if self._task:
            await self._task

    async def _loop(self):
        buffer: List[Candle] = []
        
        while self.running:
            try:
                # Collect items from queue
                try:
                    # Wait for first item
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                    buffer.append(item)
                    
                    # Drain queue up to batch size
                    while len(buffer) < self.batch_size:
                        try:
                            item = self.queue.get_nowait()
                            buffer.append(item)
                        except asyncio.QueueEmpty:
                            break
                except asyncio.TimeoutError:
                    pass # Flush interval reached
                
                # Flush if buffer has items
                if buffer:
                    await self._flush(buffer)
                    buffer = []
                    
            except Exception as e:
                logger.error(f"Error in persistence loop: {e}")
                await asyncio.sleep(1)

    async def _flush(self, candles: List[Candle]):
        """Write batch to database"""
        async with AsyncSessionLocal() as session:
            try:
                db_candles = [
                    CandleModel(
                        symbol=c.symbol,
                        timestamp=c.timestamp,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        interval=c.interval,
                        source="ostium",
                        volume=0 # Ostium provides no volume
                    ) for c in candles
                ]
                
                session.add_all(db_candles)
                await session.commit()
                logger.debug(f"💾 Persisted {len(db_candles)} candles")
                
            except Exception as e:
                logger.error(f"Failed to persist batch: {e}")
                await session.rollback()
