from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any, Optional
import logging
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

@router.get("/hyperliquid/prices")
async def get_hyperliquid_prices():
    try:
        from main import hl_price_history
        
        # Use connector's fetch_all_markets method which handles:
        # - Filtering delisted assets
        # - Filtering zero-volume markets
        # - Category mapping
        # - Data normalization
        markets = await hl_connector.fetch_all_markets()
        
        # Update price history tracker and get high/low stats
        for market in markets:
            symbol = market["symbol"]
            price = market["price"]
            
            # Update price history
            hl_price_history.update_price(symbol, price)
            
            # Get 24h stats for high/low
            stats_24h = hl_price_history.get_stats(symbol)
            
            # Update high/low values (keep existing change/volume from connector)
            if stats_24h:
                market["high_24h"] = stats_24h.get("high_24h", 0)
                market["low_24h"] = stats_24h.get("low_24h", 0)
            else:
                market["high_24h"] = 0
                market["low_24h"] = 0
        
        return markets
        
    except Exception as e:
        logger.error(f"Error fetching Hyperliquid prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ostium/prices")
async def get_ostium_prices():
    try:
        from main import ostium_price_history
        
        raw_prices = await ostium_client.get_latest_prices()
        if not raw_prices:
             # Fallback or empty list
             return []
        
        # Update price history tracker with latest prices
        ostium_price_history.update_from_ostium_response(raw_prices)
             
        # Normalize (returns Dict)
        normalized_dict = normalize_ostium_prices(raw_prices)
        
        # Convert to List for frontend
        markets_list = []
        for symbol, data in normalized_dict.items():
            # Get 24h stats from price history tracker
            stats_24h = ostium_price_history.get_stats(symbol)
            
            markets_list.append({
                "symbol": data["symbol"],
                "price": float(data["price"]),
                "change_24h": stats_24h.get("change_24h", 0) if stats_24h else 0,
                "change_percent_24h": stats_24h.get("change_percent_24h", 0) if stats_24h else 0,
                "volume_24h": 0,  # Ostium API doesn't provide volume data
                "high_24h": stats_24h.get("high_24h", 0) if stats_24h else 0,
                "low_24h": stats_24h.get("low_24h", 0) if stats_24h else 0,
                "category": data.get("category", "Forex")
            })
            
        return markets_list
        
    except Exception as e:
        logger.error(f"Error fetching Ostium prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))
