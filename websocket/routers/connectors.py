from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any, Optional
import logging
import asyncio
import time
import sys
import os

# Add connectors path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from connectors.hyperliquid.connector import HyperliquidConnector
from Ostium.api_client import OstiumAPIClient
from Ostium.normalizer import normalize_ostium_prices, get_ostium_category, get_ostium_max_leverage

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize connectors
hl_connector = HyperliquidConnector(config={})
ostium_client = OstiumAPIClient()

# Global cache for performance
HL_MARKETS_CACHE = []
OST_MARKETS_CACHE = []
LAST_HL_UPDATE = 0
LAST_OST_UPDATE = 0

async def update_hl_cache():
    global HL_MARKETS_CACHE, LAST_HL_UPDATE
    try:
        from main import hl_price_history
        markets = await hl_connector.fetch_all_markets()
        if markets:
            for market in markets:
                symbol = market["symbol"]
                price = market["price"]
                hl_price_history.update_price(symbol, price)
                stats_24h = hl_price_history.get_stats(symbol)
                if stats_24h:
                    market["high_24h"] = stats_24h.get("high_24h", 0)
                    market["low_24h"] = stats_24h.get("low_24h", 0)
            HL_MARKETS_CACHE = markets
            LAST_HL_UPDATE = time.time()
    except Exception as e:
        logger.error(f"Error updating HL cache: {e}")

async def update_ost_cache():
    global OST_MARKETS_CACHE, LAST_OST_UPDATE
    try:
        from main import ostium_price_history
        raw_prices = await ostium_client.get_latest_prices()
        if raw_prices:
            ostium_price_history.update_from_ostium_response(raw_prices)
            normalized_dict = normalize_ostium_prices(raw_prices)
            markets_list = []
            for symbol, data in normalized_dict.items():
                stats_24h = ostium_price_history.get_stats(symbol)
                markets_list.append({
                    "symbol": data["symbol"],
                    "price": float(data["price"]),
                    "change_24h": stats_24h.get("change_24h", 0) if stats_24h else 0,
                    "change_percent_24h": stats_24h.get("change_percent_24h", 0) if stats_24h else 0,
                    "volume_24h": 0,
                    "high_24h": stats_24h.get("high_24h", 0) if stats_24h else 0,
                    "low_24h": stats_24h.get("low_24h", 0) if stats_24h else 0,
                    "category": data.get("category", "Forex")
                })
            OST_MARKETS_CACHE = markets_list
            LAST_OST_UPDATE = time.time()
    except Exception as e:
        logger.error(f"Error updating Ostium cache: {e}")

@router.on_event("startup")
async def start_cache_poller():
    async def poll():
        while True:
            await asyncio.gather(update_hl_cache(), update_ost_cache())
            await asyncio.sleep(0.5) # Refresh every 0.5s for <1s freshness
    asyncio.create_task(poll())

@router.get("/hyperliquid/prices")
async def get_hyperliquid_prices():
    if not HL_MARKETS_CACHE:
        await update_hl_cache()
    return HL_MARKETS_CACHE

@router.get("/ostium/prices")
async def get_ostium_prices():
    if not OST_MARKETS_CACHE:
        await update_ost_cache()
    return OST_MARKETS_CACHE
