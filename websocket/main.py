from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# Trigger Reload 1
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram
import signal
import sys
import os
import logging
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Dict, Set, List, Any
import httpx

from config import settings
from Hyperliquid.websocket_client import HyperliquidWebSocketClient
from Hyperliquid.http_client import http_client
from Hyperliquid.normalizer import normalize_all_mids
from Ostium.api_client import OstiumAPIClient
from Ostium.poller import OstiumPoller
from Ostium.normalizer import normalize_ostium_prices
from Ostium.price_history import PriceHistoryTracker
from Ostium.candles import CandleGenerator
from Ostium.persistence import CandlePersister
from Ostium.subgraph_client import OstiumSubgraphClient  # New
from sqlalchemy import text
from database.connection import init_db, AsyncSessionLocal
from database.models import Candle, Trade
from storage.redis_manager import redis_manager

# Import connector system
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from connectors.init_connectors import connector_registry
from connectors.web3_arbitrum.api_routes import router as web3_router
from connectors.hyperliquid.category_map import get_category  # Import category mapping

# Import orders API
from routers.orders import router as orders_router
from services.price_pusher import price_pusher
from services.price_monitor_service import price_monitor_service
from services.ai_trigger_service import ai_trigger_service
from services.session_candle_cache import (
    session_candle_cache,
    to_timeframe,
    is_cache_timeframe,
    to_hl_interval,
    timeframe_minutes,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
from prometheus_client import REGISTRY, Counter, Gauge, Histogram

# Clear existing metrics if they exist to avoid duplication errors during reloads
for metric in ['osmo_http_requests_total', 'osmo_ws_connections', 'osmo_api_latency_seconds']:
    try:
        # Check if metric is already in the registry
        # We need to access the protected _names_to_collectors mapping
        if metric in REGISTRY._names_to_collectors:
            collector = REGISTRY._names_to_collectors[metric]
            REGISTRY.unregister(collector)
    except Exception:
        pass

http_requests_total = Counter('osmo_http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
active_connections = Gauge('osmo_ws_connections', 'Active WebSocket connections', ['module', 'symbol'])
request_latency = Histogram('osmo_api_latency_seconds', 'API request latency', ['endpoint'])

# Global state
hyperliquid_client: HyperliquidWebSocketClient = None
ostium_client: OstiumAPIClient = None
ostium_poller: OstiumPoller = None
ostium_subgraph: OstiumSubgraphClient = None # New
ostium_price_history: PriceHistoryTracker = PriceHistoryTracker()
hl_price_history: PriceHistoryTracker = PriceHistoryTracker() # Tracker for HL high/low
ostium_candle_generator: CandleGenerator = CandleGenerator()
ostium_persister: CandlePersister = None # Will be initialized in lifespan
connected_clients: Dict[str, Set[WebSocket]] = {}  # symbol -> set of websockets
connected_l2book_clients: Dict[str, Set[WebSocket]] = {}
connected_trades_clients: Dict[str, Set[WebSocket]] = {}
latest_prices: Dict[str, dict] = {}  # symbol -> latest price data
_COMMODITY_BASES = {"XAU", "XAG", "WTI", "BRN", "NG", "GC", "SI", "HG", "CL"}
_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


async def _fetch_binance_candles(
    symbol: str,
    timeframe: str,
    start_time: int,
    end_time: int,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Fallback candles from Binance (USDT pairs) for crypto symbols.
    """
    tf = to_timeframe(timeframe or "1m")
    interval_map = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
        "1w": "1w",
    }
    interval = interval_map.get(tf)
    if not interval:
        return []

    base = (symbol or "").upper().replace("/", "-").replace("_", "-").split("-")[0]
    if not base:
        return []
    pair = f"{base}USDT"

    safe_limit = max(1, int(limit))
    step_ms = max(60_000, timeframe_minutes(tf) * 60 * 1000)
    cursor = max(0, int(start_time))
    end_ms = max(cursor, int(end_time))
    out: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        while cursor <= end_ms and len(out) < safe_limit:
            params = {
                "symbol": pair,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": min(1000, safe_limit - len(out)),
            }
            try:
                rows = await session_candle_cache._json_get_with_ssl_fallback(
                    client, _BINANCE_KLINES_URL, params
                )
            except Exception as exc:
                logger.warning("Binance fallback failed for %s (%s): %s", symbol, tf, exc)
                break

            if not isinstance(rows, list) or not rows:
                break

            last_open = None
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                ts = int(row[0])
                out.append(
                    {
                        "timestamp": ts,
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                        "symbol": symbol,
                    }
                )
                last_open = ts
                if len(out) >= safe_limit:
                    break

            if last_open is None:
                break
            next_cursor = last_open + step_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            await asyncio.sleep(0.03)

    return out[-safe_limit:]


async def handle_hyperliquid_message(data: dict):
    """Handle incoming messages from Hyperliquid and broadcast to connected clients"""
    global latest_prices
    
    normalized = normalize_all_mids(data)

    # Keep session candle cache in sync from primary stream (in-memory only).
    if settings.SECONDARY_HISTORY_ENABLED:
        for symbol, payload in normalized.items():
            try:
                session_candle_cache.update_tick(
                    symbol=symbol,
                    price=float(payload.get("price", 0)),
                    timestamp_ms=int(payload.get("timestamp", int(time.time() * 1000))),
                )
            except Exception:
                continue
    
    # Preserve 24h stats from existing state
    for symbol, new_data in normalized.items():
        # Update price history tracker
        if "price" in new_data:
            hl_price_history.update_price(symbol, float(new_data["price"]))

    # Update latest_prices and enrich normalized data with stats
    for symbol, data in normalized.items():
        if symbol in latest_prices:
            latest_prices[symbol].update(data)
            # Inject stats into the broadcast message so frontend gets them
            current_stats = latest_prices[symbol]
            data["high_24h"] = current_stats.get("high_24h", 0)
            data["low_24h"] = current_stats.get("low_24h", 0)
            data["volume_24h"] = current_stats.get("volume_24h", 0)
            data["change_24h"] = current_stats.get("change_24h", 0)
            data["change_24h"] = current_stats.get("change_24h", 0)
            data["change_percent_24h"] = current_stats.get("change_percent_24h", 0)
            data["maxLeverage"] = current_stats.get("maxLeverage", 50)
            data["category"] = current_stats.get("category", "Crypto")
        else:
            # New symbol from WS - Initialize with defaults
            # Extract coin from symbol (e.g., "BTC-USD" -> "BTC")
            coin = symbol.split("-")[0]
            data["category"] = get_category(coin)
            data["maxLeverage"] = 0 # Default until poll_hyperliquid_stats updates it
            data["high_24h"] = 0
            data["low_24h"] = 0
            data["volume_24h"] = 0
            data["change_24h"] = 0
            data["change_percent_24h"] = 0
            latest_prices[symbol] = data
    
    # Update price monitor service with latest prices
    price_monitor_service.update_prices(latest_prices)
    
    # Broadcast to "ALL" subscribers (global stream)
    if "ALL" in connected_clients and normalized:
        try:
            # OPTIMIZATION: Only send the CHANGED data (normalized), not the full state
            # This prevents overwhelming the client and filling the WS buffer
            all_message = json.dumps({
                "type": "price_update",
                "data": normalized
            })
            disconnected = set()
            for client in list(connected_clients["ALL"]):
                try:
                    await client.send_text(all_message)
                except Exception as e:
                    logger.error(f"Failed to send to ALL client: {e}")
                    disconnected.add(client)
            connected_clients["ALL"] -= disconnected
        except Exception as json_err:
            logger.error(f"JSON serialization error in HL broadcast: {json_err}")
    
    # Broadcast to connected clients (per symbol)
    for symbol, price_data in normalized.items():
        if symbol in connected_clients:
            try:
                message = json.dumps({
                    "type": "price_update",
                    "data": price_data
                })
                
                # Broadcast to all clients subscribed to this symbol
                disconnected = set()
                for client in list(connected_clients[symbol]):
                    try:
                        await client.send_text(message)
                    except Exception as e:
                        logger.error(f"Failed to send to client: {e}")
                        disconnected.add(client)
                
                # Remove disconnected clients
                connected_clients[symbol] -= disconnected
            except Exception as e:
                logger.error(f"Error broadcasting symbol {symbol}: {e}")


async def handle_l2book_message(data: dict):
    """Handle incoming L2 Orderbook data"""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Handling L2Book message: {str(data)[:100]}...")

    coin = data.get("coin")
    if not coin:
        logger.warning(f"âš ï¸ L2Book data missing 'coin' field: {data.keys()}")
        return
        
    symbol = f"{coin}-USD" # Normalize
    message = json.dumps({
        "type": "l2Book",
        "data": data,
        "symbol": symbol
    })
    
    # Broadcast to WebSocket clients
    if symbol in connected_l2book_clients:
        disconnected = set()
        for client in list(connected_l2book_clients[symbol]):
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)
        connected_l2book_clients[symbol] -= disconnected

    # Publish to Redis
    try:
        await redis_manager.publish(f"orderbook:{symbol}", message)
    except Exception:
        pass


async def handle_trades_message(data: dict):
    """Handle incoming Trades data"""
    # trades data is usually a list of trades
    if not isinstance(data, list) or not data:
        logger.warning(f"âš ï¸ Trades data is not a non-empty list: {type(data)}")
        return
        
    coin = data[0].get("coin")
    if not coin:
        logger.warning(f"âš ï¸ Trades data missing 'coin' field in first element: {data[0].keys()}")
        return

    symbol = f"{coin}-USD"
    message = json.dumps({
        "type": "trades",
        "data": data,
        "symbol": symbol
    })
    
    # Broadcast to WebSocket clients
    if symbol in connected_trades_clients:
        disconnected = set()
        for client in list(connected_trades_clients[symbol]):
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)
        connected_trades_clients[symbol] -= disconnected

    # Publish to Redis
    try:
        await redis_manager.publish(f"trades:{symbol}", message)
    except Exception:
        pass


async def handle_ostium_message(data: dict):
    """Handle incoming Ostium price data and broadcast to connected clients"""
    global latest_prices, ostium_price_history, ostium_candle_generator
    
    # Update price history tracker
    if isinstance(data, list):
        ostium_price_history.update_from_ostium_response(data)
    
    normalized = normalize_ostium_prices(data)
    
    # FILTER: Skip crypto markets in Ostium handler (We use Hyperliquid for Crypto)
    crypto_skips = {'BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD', 'BNB-USD', 'LINK-USD', 'TRX-USD', 'XRP-USD', 'HYPE-USD', 'GLXY-USD', 'BMNR-USD', 'CRCL-USD', 'SBET-USD', 'SUI-USD'}
    filtered_normalized = {}

    # Process each symbol
    for symbol, price_data in normalized.items():
        if symbol in crypto_skips:
            continue
            
        filtered_normalized[symbol] = price_data

        if settings.SECONDARY_HISTORY_ENABLED:
            try:
                session_candle_cache.update_tick(
                    symbol=symbol,
                    price=float(price_data.get("price", 0)),
                    timestamp_ms=int(price_data.get("timestamp", int(time.time() * 1000))),
                )
            except Exception:
                pass
        
        # 1. Update Candle Generator
        try:
            price = float(price_data["price"])
            timestamp = price_data["timestamp"]
            ostium_candle_generator.update_price(symbol, price, timestamp)
        except Exception as e:
            logger.error(f"Failed to update candle for {symbol}: {e}")

        # 2. Add 24h stats
        stats = ostium_price_history.get_stats(symbol)
        if stats:
            # Stats fields mapping
            price_data["change_24h"] = stats.get("change_24h", 0)
            price_data["change_percent_24h"] = stats.get("change_percent_24h", 0)
            price_data["high_24h"] = stats.get("high_24h")
            price_data["low_24h"] = stats.get("low_24h")
            
        # 3. Add Mark Price (For Ostium, Price = Mark Price)
        price_data["markPrice"] = price_data["price"]
        
        # 4. PRESERVE fields from existing state
        if symbol in latest_prices:
            existing = latest_prices[symbol]
            # Copy volume data if not present in new update
            if "volume_24h" in existing and price_data.get("volume_24h") is None:
                price_data["volume_24h"] = existing["volume_24h"]
            if "openInterest" in existing and "openInterest" not in price_data:
                price_data["openInterest"] = existing["openInterest"]
            if "utilization" in existing and "utilization" not in price_data:
                price_data["utilization"] = existing["utilization"]
    
    latest_prices.update(filtered_normalized)
    
    # Broadcast to "ALL" subscribers (global stream)
    if "ALL" in connected_clients and filtered_normalized:
        try:
            # OPTIMIZATION: Only send the CHANGED data (filtered_normalized), not the full state
            all_message = json.dumps({
                "type": "price_update",
                "data": filtered_normalized
            })
            disconnected = set()
            for client in list(connected_clients["ALL"]):
                try:
                    await client.send_text(all_message)
                except Exception as e:
                    logger.error(f"Failed to send to ALL client (Ostium): {e}")
                    disconnected.add(client)
            connected_clients["ALL"] -= disconnected
        except Exception as json_err:
            logger.error(f"JSON serialization error in Ostium broadcast: {json_err}")

    # Broadcast to connected clients (per symbol)
    for symbol, price_data in filtered_normalized.items():
        if symbol in connected_clients:
            try:
                message = json.dumps({
                    "type": "price_update",
                    "data": price_data
                })
                
                disconnected = set()
                for client in list(connected_clients[symbol]):
                    try:
                        await client.send_text(message)
                    except Exception as e:
                        logger.error(f"Failed to send to client {symbol}: {e}")
                        disconnected.add(client)
                
                connected_clients[symbol] -= disconnected
            except Exception as e:
                logger.error(f"Error broadcasting symbol {symbol} from Ostium: {e}")


async def poll_ostium_volume():
    """Periodically fetch volume/OI data from Ostium Subgraph"""
    global latest_prices, ostium_subgraph
    
    while True:
        try:
            if ostium_subgraph:
                logger.debug("Polling Ostium Subgraph for Volume/OI...")
                # Add timeout
                pairs_data = await asyncio.wait_for(ostium_subgraph.get_formatted_pairs_details(), timeout=30.0)
                
                count = 0
                for item in pairs_data:
                    symbol = item['symbol']
                    
                    # FILTER: Skip crypto markets in Ostium poller (We use Hyperliquid for Crypto)
                    # This prevents overwriting HL's high volume data with Ostium's low OI data
                    s_clean = symbol.upper().replace("-", "")
                    crypto_skips = ['ADAUSD', 'BNBUSD', 'BTCUSD', 'ETHUSD', 'LINKUSD', 'SOLUSD', 'TRXUSD', 'XRPUSD', 'HYPEUSD', 'GLXYUSD', 'BMNRUSD', 'CRCLUSD', 'SBETUSD', 'SUIUSD']
                    if s_clean in crypto_skips:
                        continue
                    
                    # Ensure entry exists
                    if symbol not in latest_prices:
                        latest_prices[symbol] = {
                            "symbol": symbol,
                            "price": 0,
                            "price": 0,
                            "source": "ostium",
                            "maxLeverage": 100, # Default for Forex/Commodities on Ostium
                            "timestamp": int(time.time() * 1000)
                        }
                    
                    # Use Total OI as a proxy for "Volume" / Market Size
                    latest_prices[symbol]["volume_24h"] = item['totalOI'] 
                    latest_prices[symbol]["openInterest"] = item['totalOI']
                    latest_prices[symbol]["utilization"] = item['utilization']
                    latest_prices[symbol]["openInterest"] = item['totalOI']
                    latest_prices[symbol]["utilization"] = item['utilization']
                    latest_prices[symbol]["source"] = "ostium" 
                    latest_prices[symbol]["maxLeverage"] = 100 # Ensure present update
                    
                    # Add 24h stats from history
                    stats = ostium_price_history.get_stats(symbol)
                    if stats:
                        latest_prices[symbol]["change_24h"] = stats.get("change_24h", 0)
                        latest_prices[symbol]["change_percent_24h"] = stats.get("change_percent_24h", 0)
                        latest_prices[symbol]["high_24h"] = stats.get("high_24h")
                        latest_prices[symbol]["low_24h"] = stats.get("low_24h")
                    
                    count += 1
                
                if count > 0:
                    logger.info(f"âœ… Updated volume/OI for {count} Ostium symbols")
                else:
                    logger.warning(f"âš ï¸ Polled Ostium Subgraph but found 0 matches in latest_prices. (Total pairs: {len(pairs_data)})")
                    
        except Exception as e:
            logger.error(f"âŒ Error in volume poller: {e}")
            
        await asyncio.sleep(30)  # Poll every 30s


async def poll_hyperliquid_stats():
    """Periodically fetch 24h stats for Hyperliquid (Volume, OI)"""
    global latest_prices
    
    while True:
        try:
            logger.info("Polling Hyperliquid stats (Volume, OI, etc)...")
            # Add timeout
            data = await asyncio.wait_for(http_client.get_meta_and_asset_ctxs(), timeout=30.0)
            
            if data and len(data) == 2:
                meta = data[0]
                ctxs = data[1]
                universe = meta.get("universe", [])
                
                count = 0
                for i, asset_info in enumerate(universe):
                    if i < len(ctxs):
                        coin = asset_info["name"]
                        ctx = ctxs[i]
                        symbol = f"{coin}-USD"
                        
                        # Extract maxLeverage from universe info
                        max_leverage = asset_info.get("maxLeverage", 50)
                        
                        # Ensure entry exists
                        if symbol not in latest_prices:
                            latest_prices[symbol] = {
                                "symbol": symbol,
                                "price": float(ctx.get("midPx") or ctx.get("markPx") or 0),
                                "source": "hyperliquid",
                                "category": get_category(coin),  # Add category
                                "maxLeverage": max_leverage,
                                "timestamp": int(time.time() * 1000)
                            }
                        else:
                            # Re-assert source to be sure
                            latest_prices[symbol]["source"] = "hyperliquid"
                            latest_prices[symbol]["category"] = get_category(coin)  # Add category
                            latest_prices[symbol]["maxLeverage"] = max_leverage
                        
                        # dayNtlVlm is 24h volume
                        latest_prices[symbol]["volume_24h"] = float(ctx.get("dayNtlVlm", 0))
                        latest_prices[symbol]["openInterest"] = float(ctx.get("openInterest", 0))
                        
                        # premium/funding could also be added here
                        latest_prices[symbol]["funding"] = float(ctx.get("funding", 0))

                        # Calculate 24h Change
                        try:
                            prev_day_px = float(ctx.get("prevDayPx", 0))
                            mark_px = float(ctx.get("markPx", 0))
                            if prev_day_px > 0:
                                change_abs = mark_px - prev_day_px
                                change_pct = (change_abs / prev_day_px) * 100
                                
                                latest_prices[symbol]["change_24h"] = change_abs
                                latest_prices[symbol]["change_percent_24h"] = change_pct
                        except Exception:
                            pass
                            
                        # Add High/Low from tracker
                        hl_stats = hl_price_history.get_stats(symbol)
                        if hl_stats:
                            if hl_stats.get("high_24h"):
                                latest_prices[symbol]["high_24h"] = hl_stats["high_24h"]
                            if hl_stats.get("low_24h"):
                                latest_prices[symbol]["low_24h"] = hl_stats["low_24h"]
                        
                        count += 1
                
                if count > 0:
                     logger.info(f"Updated stats for {count} Hyperliquid assets")
                     
        except Exception as e:
            logger.error(f"Error polling Hyperliquid stats: {e}")
            
        await asyncio.sleep(60)  # Poll every 60s


async def bootstrap_hyperliquid_history():
    """Initial fetch of 24h high/low for all Hyperliquid assets via candles"""
    global latest_prices, hl_price_history
    
    logger.info("âš¡ Bootstrapping Hyperliquid High/Low history...")
    try:
        data = await http_client.get_meta_and_asset_ctxs()
        if data and len(data) == 2:
            universe = data[0].get("universe", [])
            
            # Limit to top assets or process in chunks to avoid rate limits
            for i, asset in enumerate(universe):
                coin = asset["name"]
                symbol = f"{coin}-USD"
                try:
                    # Extract Max Leverage
                    max_leverage = asset.get("maxLeverage", 50) # Use 50 as fallback if missing, but should be there

                    # Fetch 1d candle for current high/low
                    candles = await http_client.get_candles(coin, interval="1d")
                    if candles:
                        latest_candle = candles[-1]
                        high = float(latest_candle.get("high", 0))
                        low = float(latest_candle.get("low", 0))
                        
                        if high > 0:
                            hl_price_history.update_price(symbol, high)
                        if low > 0:
                            hl_price_history.update_price(symbol, low)
                            
                        # Ensure latest_prices has the data, initializing if needed
                        if symbol not in latest_prices:
                            latest_prices[symbol] = {
                                "symbol": symbol, 
                                "source": "hyperliquid",
                                "category": get_category(coin),  # Add category
                                "maxLeverage": max_leverage,     # Add maxLeverage
                                "price": 0, # Will be updated by WS
                                "change_24h": 0,
                                "change_percent_24h": 0,
                                "volume_24h": 0
                            }
                        else:
                             latest_prices[symbol]["category"] = get_category(coin)
                             latest_prices[symbol]["maxLeverage"] = max_leverage
                        
                        latest_prices[symbol]["high_24h"] = high
                        latest_prices[symbol]["low_24h"] = low
                    
                    # Small delay to be polite to the API
                    if i % 10 == 0:
                        await asyncio.sleep(1)
                        
                except Exception as e:
                    # logger.warning(f"Failed to bootstrap {coin}: {e}")
                    continue
            
            logger.info(f"âœ… Bootstrapped High/Low for {len(universe)} HL symbols")
    except Exception as e:
        logger.error(f"âŒ Error bootstrapping HL history: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events"""
    global hyperliquid_client, ostium_client, ostium_poller, ostium_subgraph, ostium_candle_generator, ostium_persister
    
    # Startup
    logger.info("ðŸš€ Starting Osmo Backend...")
    logger.info(f"Environment: {settings.ENV}")
    
    # Load persistence only when explicitly allowed (dev mode is in-memory only).
    if not settings.WS_IN_MEMORY_ONLY:
        ostium_price_history.load_from_disk()
        hl_price_history.load_from_disk("/tmp/hl_history_snapshot.json")
    
    # Initialize candle generator and optional DB persister.
    if settings.WS_IN_MEMORY_ONLY:
        ostium_candle_generator = CandleGenerator(queue=None)
        ostium_persister = None
    else:
        candle_queue = asyncio.Queue()
        ostium_candle_generator = CandleGenerator(queue=candle_queue)
        ostium_persister = CandlePersister(queue=candle_queue)
        await ostium_persister.start()
    
    # Initialize Redis
    try:
        await redis_manager.connect()
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
    
    # Start Bridge Monitor - REMOVED (Not implemented)
    # await bridge_monitor.start()

    # Start Hyperliquid WebSocket client
    try:
        ws_url = settings.HYPERLIQUID_WS_URL or "wss://api.hyperliquid.xyz/ws"
        logger.info(f"ðŸ”Œ Connecting to Hyperliquid WS at: {ws_url}")
        
        hyperliquid_client = HyperliquidWebSocketClient(ws_url)
        await hyperliquid_client.connect()
        logger.info("âœ… Connection established, subscribing to allMids...")
        
        await hyperliquid_client.subscribe("allMids", handle_hyperliquid_message)
        logger.info("âœ… Subscribed to allMids, starting listen loop...")
        
        asyncio.create_task(hyperliquid_client.listen())
        logger.info("âœ… Hyperliquid WebSocket client started successfully")
    except Exception as e:
        logger.error(f"âŒ Failed to start Hyperliquid client: {e}", exc_info=True)
        
    # Start Hyperliquid Stats Poller & Bootstrap
    asyncio.create_task(poll_hyperliquid_stats())
    asyncio.create_task(bootstrap_hyperliquid_history())

    if settings.SECONDARY_HISTORY_ENABLED and settings.SECONDARY_HISTORY_PREWARM:
        # Never block app startup on optional secondary history prewarm. Some fetch paths can be slow or
        # use blocking I/O in dependencies, which would prevent Uvicorn from completing startup.
        logger.info("Prewarming in-memory session candle cache in background...")

        def _run_prewarm() -> None:
            try:
                asyncio.run(session_candle_cache.prewarm_default_symbols())
                logger.info("In-memory session candle cache prewarmed (background)")
            except Exception as prewarm_err:
                logger.warning(f"Session candle cache prewarm failed (background): {prewarm_err}")

        asyncio.create_task(asyncio.to_thread(_run_prewarm))
    
    # Start Ostium API poller
    try:
        ostium_client = OstiumAPIClient(settings.OSTIUM_API_URL)
        ostium_poller = OstiumPoller(
            api_client=ostium_client,
            poll_interval=settings.OSTIUM_POLL_INTERVAL,
            callback=handle_ostium_message
        )
        await ostium_poller.start()
        
        # Start Ostium Subgraph Volume Poller (SDK)
        try:
            ostium_subgraph = OstiumSubgraphClient()
            asyncio.create_task(poll_ostium_volume())
            logger.info(f"âœ… Ostium Subgraph Poller started")
        except Exception as e:
            logger.error(f"âš ï¸ Failed to start Subgraph Poller: {e}")
            
        logger.info(f"âœ… Ostium poller started (interval: {settings.OSTIUM_POLL_INTERVAL}s)")
        
        # Start Price Pusher (Sync to on-chain OrderRouter) - DISABLED (Using JIT Push in OnchainConnector)
        # asyncio.create_task(price_pusher.start(latest_prices, connected_clients))
        # logger.info("âœ… Price Pusher started")
    except Exception as e:
        logger.error(f"âŒ Failed to start Ostium poller: {e}")

    # Start Indexer Service (Hybrid Architecture)
    try:
        print("DEBUG: Loading indexer_service...")
        from services.indexer_service import indexer_service
        print("DEBUG: Starting indexer_service task...")
        asyncio.create_task(indexer_service.start())
        logger.info("âœ… Indexer Service started (Listening to On-Chain Events)")
        
        # Start Simulation Matching Engine
        print("DEBUG: Loading matching_engine...")
        from services.matching_engine import simulation_matching_engine
        print("DEBUG: Starting matching_engine task...")
        asyncio.create_task(simulation_matching_engine.start())
        logger.info("âœ… Simulation Matching Engine started")
        
        # Start Price Monitor Service (GP/GL monitoring)
        try:
            from services.ai_trigger_service import ai_trigger_service
            ai_callback = await ai_trigger_service.create_ai_trigger_callback()
            price_monitor_service.set_ai_trigger_callback(ai_callback)
            await price_monitor_service.start(latest_prices)
            logger.info("âœ… Price Monitor Service started (GP/GL monitoring)")
        except Exception as e:
            logger.error(f"âŒ Failed to start Price Monitor Service: {e}")
        
    except Exception as e:
        logger.error(f"âŒ Failed to start Indexer/Matching Services: {e}")

    # Initialize Connector System
    try:
        asyncio.create_task(connector_registry.initialize(redis_url=settings.REDIS_URL))
        logger.info("âœ… Connector system initialized")
    except Exception as e:
        logger.error(f"âŒ Failed to initialize connector system: {e}")
    
    # Initialize Database
    try:
        await init_db()
        logger.info("âœ… Database initialized")
        
        # CLEAR TABLES FOR DEVELOPMENT (Per user request: store temporarily)
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("TRUNCATE TABLE candles RESTART IDENTITY CASCADE"))
                await session.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
                # Also truncate new trading tables if they exist
                try:
                    pass 
                    # await session.execute(text("TRUNCATE TABLE orders RESTART IDENTITY CASCADE"))
                    # await session.execute(text("TRUNCATE TABLE positions RESTART IDENTITY CASCADE"))
                except Exception:
                    pass
                await session.commit()
                logger.info("ðŸ§¹ Development: Markets and Trading tables cleared for new session")
        except Exception as truncate_err:
            logger.warning(f"âš ï¸ Failed to clear some tables: {truncate_err}")
            
    except Exception as e:
        logger.error(f"âŒ Database initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("ðŸ›‘ Shutting down Osmo Backend...")
    
    # CLEAR TABLES ON EXIT (Per user request)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("TRUNCATE TABLE candles RESTART IDENTITY CASCADE"))
            await session.execute(text("TRUNCATE TABLE trades RESTART IDENTITY CASCADE"))
            try:
                pass
                # await session.execute(text("TRUNCATE TABLE orders RESTART IDENTITY CASCADE"))
                # await session.execute(text("TRUNCATE TABLE positions RESTART IDENTITY CASCADE"))
            except Exception:
                pass
            await session.commit()
            logger.info("ðŸ§¹ Development: Tables cleared on shutdown")
    except Exception as e:
        logger.error(f"âš ï¸ Failed to clear tables on shutdown: {e}")
    
    if not settings.WS_IN_MEMORY_ONLY:
        ostium_price_history.save_to_disk()
        hl_price_history.save_to_disk("/tmp/hl_history_snapshot.json")
    
    # Shutdown connector system
    await connector_registry.shutdown()
    
    # Stop price monitor service
    await price_monitor_service.stop()
    
    if hyperliquid_client:
        await hyperliquid_client.disconnect()
    
    await redis_manager.disconnect()
    
    if ostium_persister:
        await ostium_persister.stop()

    if ostium_poller:
        await ostium_poller.stop()
    if ostium_client:
        await ostium_client.close()
    if ostium_subgraph:
        await ostium_subgraph.close()
    logger.info("âœ… Shutdown complete")


# Initialize FastAPI
app = FastAPI(
    title="Osmo API",
    description="Trading & AI Agent API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
app.include_router(web3_router, prefix="/api/v1", tags=["web3"])

# Add Prometheus metrics to FastAPI
# We need to expose /metrics endpoint
from starlette.responses import Response
import time

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")

# Include Routers
from routers.user import router as user_router
from routers.leaderboard import router as leaderboard_router
from routers.orders import router as orders_router
from connectors.web3_arbitrum.api_routes import router as web3_router
from routers.usage import router as usage_router
from routers.portfolio import router as portfolio_router
from routers.agent import router as agent_router
from routers.markets import router as markets_router
from routers.connectors import router as connectors_router # NEW
from routers.history import router as history_router # NEW
from routers.watchlist import router as watchlist_router # NEW
from routers.tools import router as tools_router
from routers.arena import router as arena_router
from routers.trade_setups import router as trade_setups_router  # NEW: GP/GL monitoring

app.include_router(user_router, prefix="/api/user", tags=["user"])
app.include_router(leaderboard_router, prefix="/api/leaderboard", tags=["leaderboard"])
app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
app.include_router(arena_router, prefix="/api/arena", tags=["arena"])
app.include_router(web3_router, prefix="/api/v1", tags=["web3"])
app.include_router(usage_router, prefix="/api/usage", tags=["usage"])

app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(agent_router, prefix="/api/agent", tags=["agent"])
app.include_router(markets_router, prefix="/api/markets", tags=["markets"])
app.include_router(connectors_router, prefix="/api/connectors", tags=["connectors"]) # NEW: /api/connectors/hyperliquid/prices
app.include_router(history_router, prefix="/api/history", tags=["history"]) # NEW: /api/history
app.include_router(watchlist_router, tags=["watchlist"]) # NEW: /api/watchlist (prefix already in router)
app.include_router(tools_router)
app.include_router(trade_setups_router)  # NEW: /api/trade-setups (GP/GL monitoring)



# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health status"""
    hl_status = {"connected": False}
    try:
        hl_status = hyperliquid_client.get_status() if hyperliquid_client else {"connected": False}
    except Exception as e:
        logger.error(f"Health check: HL status fail: {e}")
    
    # Check Database
    db_connected = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_connected = True
    except Exception as e:
        logger.error(f"Health check: DB status fail: {e}")

    # Check Ostium
    ostium_connected = False
    try:
        if ostium_poller and ostium_poller.is_running:
            ostium_connected = True
    except Exception as e:
        logger.error(f"Health check: Ostium status fail: {e}")

    return {
        "status": "healthy",
        "hyperliquid": {
            "connected": hl_status.get("connected", False),
            "symbols": len(latest_prices),
            "subscriptions": hl_status.get("subscriptions", 0)
        },
        "ostium": {
            "connected": ostium_connected,
            "symbols": len([s for s in latest_prices if '-' in s and not s.endswith('-USD')]) , # Heuristic
            "last_poll": None 
        },
        "database": {
            "connected": db_connected
        },
        "redis": await redis_manager.get_status()
    }


# Candle history endpoint
@app.get("/api/candles/{symbol}")
async def get_candles(
    symbol: str,
    exchange: str = None,
    limit: int = 100,
    resolution: str = None,
    timeframe: str = None,
):
    """Get OHLC candles for a symbol."""
    tf = to_timeframe(timeframe or resolution or "1m")
    source_hint = exchange
    normalized_symbol = (symbol or "").upper().replace("/", "-").replace("_", "-")
    symbol_base = normalized_symbol.split("-")[0] if normalized_symbol else ""
    safe_limit = max(1, int(limit))

    if settings.SECONDARY_DISABLE_COMMODITIES and symbol_base in _COMMODITY_BASES:
        return []

    # Preferred path: session-scoped in-memory cache (secondary history + primary ticks).
    # Only use cache when requested window fits cache horizon, otherwise fallback to provider API.
    if settings.SECONDARY_HISTORY_ENABLED and is_cache_timeframe(tf):
        try:
            tf_mins = max(1, timeframe_minutes(tf))
            cache_horizon_mins = max(1, int(getattr(settings, "SESSION_HISTORY_DAYS", 4))) * 24 * 60
            requested_window_mins = safe_limit * tf_mins
            use_cache = requested_window_mins <= cache_horizon_mins

            if use_cache:
                cached = await session_candle_cache.get_candles(
                    symbol=symbol,
                    timeframe=tf,
                    limit=safe_limit,
                    source_hint=source_hint,
                )
                if cached:
                    return cached
            else:
                logger.info(
                    "Skip session cache for %s (%s): requested_window=%sm > cache_horizon=%sm",
                    symbol,
                    tf,
                    requested_window_mins,
                    cache_horizon_mins,
                )
        except Exception as cache_err:
            logger.warning("Session candle cache failed for %s (%s): %s", symbol, tf, cache_err)

    # Shared external window
    end_time = int(time.time() * 1000)
    tf_mins = timeframe_minutes(tf)
    start_time = end_time - (safe_limit * tf_mins * 60 * 1000)
    interval = to_hl_interval(tf)
    coin = symbol.split("-")[0]

    # Fallback path (legacy)
    if exchange == "ostium":
        if symbol in ostium_candle_generator.candles or symbol in ostium_candle_generator.current_candles:
            logger.info("Fetching %s Ostium candles for %s", safe_limit, symbol)
            raw = ostium_candle_generator.get_candles(symbol, safe_limit if tf == "1m" else safe_limit * 30)
            if tf == "1m":
                return raw
            try:
                for item in raw:
                    session_candle_cache.update_tick(
                        symbol=symbol,
                        price=float(item.get("c", item.get("close", 0))),
                        timestamp_ms=int(item.get("t", item.get("timestamp", int(time.time() * 1000)))),
                    )
                aggregated = await session_candle_cache.get_candles(
                    symbol=symbol,
                    timeframe=tf,
                    limit=safe_limit,
                    source_hint="ostium",
                )
                if aggregated:
                    return aggregated
            except Exception:
                pass
            return raw
        logger.warning("No Ostium candles found for %s", symbol)
        return []

    if exchange == "hyperliquid":
        try:
            logger.info("Fetching %s Hyperliquid candles for %s (%s)", safe_limit, coin, interval)
            candles = await http_client.get_candles(
                coin, interval=interval, start_time=start_time, end_time=end_time
            )
            if candles:
                return candles
            logger.warning(
                "Hyperliquid returned empty candles for %s (%s), trying Binance fallback",
                symbol,
                tf,
            )
        except Exception as e:
            logger.error("Failed to fetch Hyperliquid candles for %s: %s", symbol, e)

        if symbol_base not in _COMMODITY_BASES:
            fallback = await _fetch_binance_candles(
                symbol=symbol,
                timeframe=tf,
                start_time=start_time,
                end_time=end_time,
                limit=safe_limit,
            )
            if fallback:
                logger.info("Using Binance fallback candles for %s (%s): %d bars", symbol, tf, len(fallback))
                return fallback
        return []

    # Auto-detect: Try Ostium first, then Hyperliquid
    if symbol in ostium_candle_generator.candles or symbol in ostium_candle_generator.current_candles:
        return ostium_candle_generator.get_candles(symbol, safe_limit)

    try:
        candles = await http_client.get_candles(
            coin, interval=interval, start_time=start_time, end_time=end_time
        )
        if candles:
            return candles
        logger.warning(
            "Auto source Hyperliquid returned empty candles for %s (%s), trying Binance fallback",
            symbol,
            tf,
        )
    except Exception as e:
        logger.error("Failed to fetch external candles for %s: %s", symbol, e)

    if symbol_base not in _COMMODITY_BASES:
        fallback = await _fetch_binance_candles(
            symbol=symbol,
            timeframe=tf,
            start_time=start_time,
            end_time=end_time,
            limit=safe_limit,
        )
        if fallback:
            logger.info("Using Binance fallback candles (auto) for %s (%s): %d bars", symbol, tf, len(fallback))
            return fallback
    return []
# Market info endpoint
@app.get("/api/markets")
async def get_markets():
    """List all available markets"""
    markets = []
    
    # DEBUG: Log first market keys to verify category/leverage presence
    if latest_prices:
        first_key = list(latest_prices.keys())[0]
        logger.info(f"DEBUG /api/markets sample ({first_key}): {latest_prices[first_key].keys()} | Category: {latest_prices[first_key].get('category')} | Leverage: {latest_prices[first_key].get('maxLeverage')} | Vol: {latest_prices[first_key].get('volume_24h')}")

    for symbol, data in latest_prices.items():
        markets.append({
            "symbol": symbol,
            "source": data.get("source", "hyperliquid"),
            "status": "active",
            "price": data["price"],
            **{k: v for k, v in data.items() if k not in ["symbol", "source", "price"]}
        })
    
    return {
        "total_markets": len(markets),
        "markets": markets
    }


# WebSocket endpoint for Hyperliquid price streaming
@app.websocket("/ws/hyperliquid/{symbol}")
async def hyperliquid_websocket(websocket: WebSocket, symbol: str):
    """Stream real-time Hyperliquid prices to frontend"""
    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module="hyperliquid", symbol=symbol).inc()
    
    logger.info(f"ðŸ“¡ Client connected to {symbol}")
    
    # Send latest price immediately
    try:
        if symbol == "ALL":
            logger.info(f"ðŸ“Š Sending {len(latest_prices)} keys to ALL client")
            payload = json.dumps({
                "type": "price_update",
                "data": latest_prices
            })
            await websocket.send_text(payload)
            logger.info("âœ… Initial prices sent to ALL client")
        elif symbol in latest_prices:
            # Send specific symbol price
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": latest_prices[symbol]
            }))
            logger.info(f"âœ… Initial price sent for {symbol}")
    except Exception as e:
        logger.error(f"âŒ Failed to send initial prices: {e}")
        # Don't close connection, just log the error
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Echo back for now (can add client commands later)
            logger.debug(f"Received from client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ Client disconnected from {symbol}")
    
    finally:
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module="hyperliquid", symbol=symbol).dec()


@app.websocket("/ws/ostium/{symbol}")
async def ostium_websocket(websocket: WebSocket, symbol: str):
    """Stream real-time Ostium prices to frontend"""
    await websocket.accept()
    
    # Add to connected clients
    if symbol not in connected_clients:
        connected_clients[symbol] = set()
    connected_clients[symbol].add(websocket)
    active_connections.labels(module="ostium", symbol=symbol).inc()
    
    logger.info(f"ðŸ“¡ Ostium client connected to {symbol}")
    
    # Send latest price immediately
    try:
        if symbol in latest_prices:
            await websocket.send_text(json.dumps({
                "type": "price_update",
                "data": latest_prices[symbol]
            }))
            logger.info(f"âœ… Initial Ostium price sent for {symbol}")
    except Exception as e:
        logger.error(f"âŒ Failed to send initial Ostium price: {e}")
    
    try:
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received from Ostium client: {data}")
    
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ Ostium client disconnected from {symbol}")
    
    finally:
        # Remove from connected clients
        connected_clients[symbol].discard(websocket)
        active_connections.labels(module="ostium", symbol=symbol).dec()


@app.websocket("/ws/orderbook/{symbol}")
async def orderbook_websocket(websocket: WebSocket, symbol: str):
    """Stream L2 Orderbook data"""
    await websocket.accept()
    
    coin = symbol.split("-")[0]
    
    if symbol not in connected_l2book_clients:
        connected_l2book_clients[symbol] = set()
    connected_l2book_clients[symbol].add(websocket)
    
    # Subscribe to Hyperliquid
    if hyperliquid_client and hyperliquid_client.is_connected:
        await hyperliquid_client.subscribe("l2Book", handle_l2book_message, coin=coin)
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if symbol in connected_l2book_clients:
            connected_l2book_clients[symbol].discard(websocket)


@app.websocket("/ws/trades/{symbol}")
async def trades_websocket(websocket: WebSocket, symbol: str):
    """Stream Trades data"""
    await websocket.accept()
    
    coin = symbol.split("-")[0]
    
    if symbol not in connected_trades_clients:
        connected_trades_clients[symbol] = set()
    connected_trades_clients[symbol].add(websocket)
    
    # Subscribe to Hyperliquid
    if hyperliquid_client and hyperliquid_client.is_connected:
        await hyperliquid_client.subscribe("trades", handle_trades_message, coin=coin)
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if symbol in connected_trades_clients:
            connected_trades_clients[symbol].discard(websocket)


@app.websocket("/ws/bridge/{address}")
async def bridge_websocket(websocket: WebSocket, address: str):
    """Subscribe to bridge deposit events"""
    await websocket.accept()
    
    async def send_event(data):
        try:
            await websocket.send_json(data)
        except Exception:
            pass
    
    await bridge_monitor.subscribe(address, send_event)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bridge_monitor.unsubscribe(address, send_event)


@app.websocket("/ws/notifications/{address}")
async def notification_websocket(websocket: WebSocket, address: str):
    """Subscribe to user-specific notifications (Trade fills, PnL updates, etc.)"""
    await websocket.accept()
    address = address.lower()
    
    # Send initial state
    try:
        from services.order_service import OrderService
        order_service = OrderService()
        state = await order_service.get_user_positions(address)
        await websocket.send_json({
            "type": "initial_state",
            "data": state
        })
    except Exception as e:
        logger.error(f"Error sending periodic state to {address}: {e}")

    # Subscribe to Redis for this user
    pubsub = redis_manager._redis.pubsub()
    channel = f"user_notifications:{address}"
    await pubsub.subscribe(channel)
    
    logger.info(f"ðŸ”” User {address} connected to real-time notifications")
    
    try:
        # Background task for this specific connection to listen to Redis
        async def listen_redis():
            try:
                async for message in pubsub.listen():
                    if message['type'] == 'message':
                        try:
                            # Already JSON string from LedgerService
                            # or Dict if published as dict
                            data = message['data']
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            
                            await websocket.send_text(data if isinstance(data, str) else json.dumps(data))
                        except Exception as e:
                            logger.error(f"Error relaying notification to {address}: {e}")
            except Exception as e:
                logger.error(f"Redis listener crashed for {address}: {e}")
        
        # Start redis listener as task
        redis_task = asyncio.create_task(listen_redis())
        
        # Keep connection alive
        while True:
            # Wait for client heartbeat or ignore incoming
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        logger.info(f"ðŸ“´ Notification client disconnected: {address}")
    except Exception as e:
        logger.error(f"Error in notification socket for {address}: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        if 'redis_task' in locals():
            redis_task.cancel()


# IMPORTANT:
# Do not register process-level signal handlers at import time.
# Uvicorn manages SIGTERM/SIGINT for graceful shutdown; overriding them here
# causes noisy SystemExit/CancelledError tracebacks in Docker restarts.


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Hot reload for development Haus
        log_level=settings.LOG_LEVEL.lower()
    )

