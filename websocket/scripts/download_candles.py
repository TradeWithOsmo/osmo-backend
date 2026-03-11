import asyncio
import logging
import httpx
import time
from sqlalchemy.dialects.postgresql import insert
from typing import List, Dict, Any

import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import AsyncSessionLocal
from database.models import Candle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("download_candles")

ASTER_FAPI_BASE = "https://www.asterdex.com/fapi/v1/klines"

SYMBOLS = ["BTCUSDT", "ARBUSDT"]
# Intervals for deep history
INTERVALS = ["1d", "1h", "15m", "5m", "1m"] 

async def fetch_klines(symbol: str, interval: str, start_time: int, end_time: int = None, limit: int = 1000):
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time,
        "limit": limit
    }
    if end_time:
        params["endTime"] = end_time
    
    # Simple retry logic
    for attempt in range(3):
        async with httpx.AsyncClient(verify=False) as client:
            try:
                resp = await client.get(ASTER_FAPI_BASE, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed for {symbol} {interval}: {e}")
                await asyncio.sleep(2)
    return []

async def download_symbol_data(symbol: str, interval: str, days: int = 365):
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    current_start = start_time
    all_klines = []
    
    logger.info(f"[Binance] Downloading {days} days of {interval} data for {symbol}...")
    
    while current_start < end_time:
        klines = await fetch_klines(symbol, interval, current_start, end_time)
        if not klines:
            break
            
        all_klines.extend(klines)
        # Next start is last candle's close time + 1ms
        current_start = klines[-1][6] + 1
        
        if len(klines) < 1000:
            break
            
        logger.info(f"[Binance] Collected {len(all_klines)} candles for {symbol} {interval}...")
        await asyncio.sleep(0.5) 
        
    return all_klines

async def save_to_db(klines: List[List], symbol: str, interval: str):
    internal_symbol = symbol.replace("USDT", "-USD")
    
    async with AsyncSessionLocal() as session:
        batch_size = 500
        for i in range(0, len(klines), batch_size):
            batch = klines[i:i+batch_size]
            
            # Prepare data for UPSERT
            stmt_list = []
            for k in batch:
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
            
            # UPSERT: Insert but do nothing on conflict (requires the UniqueConstraint to be applied in DB)
            stmt = insert(Candle).values(stmt_list)
            on_conflict_stmt = stmt.on_conflict_do_nothing(
                index_elements=['symbol', 'timestamp', 'interval']
            )
            
            try:
                await session.execute(on_conflict_stmt)
                await session.commit()
            except Exception as e:
                logger.error(f"Failed to upsert batch: {e}")
                await session.rollback()
        
        logger.info(f"[DB] Saved/Synced data for {internal_symbol} ({interval}).")

async def main():
    logger.info("Starting OHLC download for BTC and ARB (1 year from Binance)...")
    
    for symbol in SYMBOLS:
        for interval in INTERVALS:
            klines = await download_symbol_data(symbol, interval, days=365)
            if klines:
                await save_to_db(klines, symbol, interval)
    
    logger.info("✅ All candle data successfully synced to database.")

if __name__ == "__main__":
    asyncio.run(main())
