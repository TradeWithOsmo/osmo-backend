import logging
import httpx
import time
import asyncio
from datetime import datetime
from sqlalchemy import select, desc
from sqlalchemy.dialects.postgresql import insert
from typing import List, Dict, Any, Optional

from database.connection import AsyncSessionLocal
from database.models import Candle

logger = logging.getLogger(__name__)

# Use Aster FAPI as primary source (Binance proxy)
ASTER_FAPI_BASE = "https://www.asterdex.com/fapi/v1/klines"

class BinanceCandleService:
    """
    Service to ensure 1 year history and continuous updates for BTC & ARB klines from Binance.
    Saves data to the 'candles' table.
    """
    
    def __init__(self):
        self.symbols = ["BTCUSDT", "ARBUSDT"]
        self.intervals = ["1d", "1h", "15m", "1m"]
        self.running = False
        self._poll_task = None

    async def start(self):
        if self.running:
            return
        self.running = True
        
        # 1. Historical sync on startup (1 year)
        # asyncio.create_task(self.sync_historical_data())
        
        # 2. Continuous update loop
        self._poll_task = asyncio.create_task(self._update_loop())
        logger.info("🚀 Binance Candle Service started (BTC & ARB persistence active)")

    async def stop(self):
        self.running = False
        if self._poll_task:
            self._poll_task.cancel()
        logger.info("🛑 Binance Candle Service stopped")

    async def _update_loop(self):
        """Polls for the latest closed candles every minute"""
        while self.running:
            try:
                # Wait for just after a minute close
                now = datetime.now()
                sleep_sec = 65 - now.second # Sleep until 5 seconds into the next minute
                await asyncio.sleep(sleep_sec)
                
                for symbol in self.symbols:
                    for interval in self.intervals:
                        # Fetch last 5 candles to ensure we don't miss any due to polling lag
                        klines = await self._fetch_recent(symbol, interval, limit=5)
                        if klines:
                            await self._save_klines(klines, symbol, interval)
                            
            except Exception as e:
                logger.error(f"[BinanceCandle] Error in update loop: {e}")
                await asyncio.sleep(10)

    async def _fetch_recent(self, symbol: str, interval: str, limit: int = 5) -> List[List]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        # Disable SSL verification for VPS compatibility with Aster proxy
        async with httpx.AsyncClient(verify=False) as client:
            try:
                resp = await client.get(ASTER_FAPI_BASE, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.error(f"[BinanceCandle] Fetch {symbol} {interval} failed: {e}")
                return []

    async def _save_klines(self, klines: List[List], symbol: str, interval: str):
        internal_symbol = symbol.replace("USDT", "-USD")
        
        async with AsyncSessionLocal() as session:
            stmt_list = []
            for k in klines:
                # Binance kline index 6 is close time, but OHLC usually uses open time (index 0)
                # We skip the very last candle if it hasn't closed yet (index 0 + interval < now)
                # But for simplicity, we just UPSERT all and rely on the fact that open time is static.
                timestamp = int(k[0])
                stmt_list.append({
                    "symbol": internal_symbol,
                    "timestamp": timestamp,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "interval": interval,
                    "source": "binance"
                })
            
            # UPSERT
            stmt = insert(Candle).values(stmt_list)
            on_conflict_stmt = stmt.on_conflict_do_update(
                index_elements=['symbol', 'timestamp', 'interval'],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": "binance"
                }
            )
            
            try:
                await session.execute(on_conflict_stmt)
                await session.commit()
            except Exception as e:
                logger.error(f"[BinanceCandle] Failed to commit klines for {internal_symbol}: {e}")
                await session.rollback()

    async def get_db_candles(self, symbol: str, timeframe: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch candles from DB for indicators"""
        async with AsyncSessionLocal() as session:
            # Normalize interval
            interval = timeframe.replace("1D", "1d").replace("1H", "1h").replace("1M", "1m")
            if interval == "60": interval = "1h"
            if interval == "1": interval = "1m"
            
            clean_sym = symbol.upper().replace("/", "-")
            if "-" not in clean_sym:
                clean_sym = f"{clean_sym}-USD"
            
            stmt = select(Candle).where(
                Candle.symbol == clean_sym,
                Candle.interval == interval
            ).order_by(desc(Candle.timestamp)).limit(limit)
            
            result = await session.execute(stmt)
            db_bars = result.scalars().all()
            
            # Format for frontend
            return [
                {
                    "t": b.timestamp,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume
                } for b in reversed(db_bars)
            ]

binance_candle_service = BinanceCandleService()
