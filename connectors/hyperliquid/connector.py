"""
Hyperliquid Connector

Wrapper around existing Hyperliquid WebSocket client.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable, List
import sys
import os
import time

# Add parent directory to path to import existing websocket client
sys.path.append(os.path.join(os.path.dirname(__file__), '../../websocket'))

from Hyperliquid.websocket_client import HyperliquidWebSocketClient
from Hyperliquid.http_client import HyperliquidHTTPClient
from .category_map import get_category


class HyperliquidConnector(BaseConnector):
    """
    Hyperliquid data connector.
    
    Wraps existing websocket_client.py and http_client.py for:
    - Real-time price updates (allMids)
    - Order book L2 depth
    - Recent trades
    - User positions and orders
    - Funding rates
    - Liquidations
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("hyperliquid", config)
        
        self.ws_url = config.get("ws_url", "wss://api.hyperliquid.xyz")
        self.http_url = config.get("http_url", "https://api.hyperliquid.xyz")
        
        # Initialize clients
        self.ws_client = HyperliquidWebSocketClient(self.ws_url)
        self.http_client = HyperliquidHTTPClient(self.http_url)
        
        # Builder Settings
        self.builder_address = config.get("builder_address", os.getenv("BUILDER_ADDRESS"))
        # Default 2.5 BPS = 25 in tenths of BPS
        self.builder_fee_tenths = int(config.get("builder_fee_tenths", os.getenv("EXPECTED_KICKBACK_BPS", 25)))
        
        self.status = ConnectorStatus.HEALTHY
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch current market data for symbol via HTTP.
        
        Args:
            symbol: Trading symbol (e.g., "BTC")
            **kwargs: data_type ("price" | "orderbook" | "trades" | "funding")
        
        Returns:
            Normalized data dict
        """
        data_type = kwargs.get("data_type", "price")
        
        try:
            if data_type == "price" or data_type == "funding" or data_type == "volume":
                # Use metaAndAssetCtxs to get rich data (price, volume, funding, etc.)
                payload = {"type": "metaAndAssetCtxs"}
                response_data = await self.http_client._post(payload)
                
                # Response is [universe, assetCtxs]
                universe = response_data[0]['universe']
                asset_ctxs = response_data[1]
                
                # Find index of symbol
                asset_idx = -1
                for idx, asset in enumerate(universe):
                    if asset['name'] == symbol:
                        asset_idx = idx
                        break
                
                if asset_idx == -1:
                    raise ValueError(f"Symbol {symbol} not found in Hyperliquid universe")
                
                ctx = asset_ctxs[asset_idx]
                
                # Calculate 24h stats
                # Calculate 24h stats with fallback
                current_price = float(ctx.get('midPx') or ctx.get('markPx') or ctx.get('oraclePx') or 0)
                prev_day_price = float(ctx.get('prevDayPx') or 0)
                
                # Only calculate change if we have both prices
                if current_price > 0 and prev_day_price > 0:
                    change_24h = current_price - prev_day_price
                    change_percent_24h = (change_24h / prev_day_price * 100)
                else:
                    change_24h = 0
                    change_percent_24h = 0
                
                # Construct data based on requested type
                if data_type == "price":
                    return self.normalize({
                        "coin": symbol,
                        "mid": ctx.get('midPx'),
                        "markPx": ctx.get('markPx'),
                        "oraclePx": ctx.get('oraclePx'),
                        "change_24h": change_24h,
                        "change_percent_24h": change_percent_24h,
                        "open_interest": ctx.get('openInterest'),
                        "volume_24h": ctx.get('dayNtlVlm') # Notional volume (USD)
                    }, "price")
                    
                elif data_type == "funding":
                    return self.normalize({
                        "coin": symbol, 
                        "funding": ctx.get('funding'),
                        "premium": ctx.get('premium'),
                        "next_funding_time": 0 # Not explicitly in this endpoint, usually hourly
                    }, "funding")
                    
                elif data_type == "volume":
                     return self.normalize({
                        "coin": symbol,
                        "volume_24h": ctx.get('dayNtlVlm'),
                        "volume_base": ctx.get('dayBaseVlm')
                    }, "volume")

            elif data_type == "orderbook":
                # Get L2 orderbook via meta endpoint
                payload = {
                    "type": "l2Book",
                    "coin": symbol
                }
                raw_data = await self.http_client._post(payload)
                return self.normalize(raw_data, "orderbook")
            
            elif data_type == "trades":
                # Get recent trades - not directly available, use candles as proxy
                # Real implementation would use the specific trades endpoint if available via REST, 
                # but Hyperliquid mostly pushes trades via WS. Candles is a decent fallback for "recent history".
                candles = await self.http_client.get_candles(symbol, interval="1m")
                raw_data = {"trades": candles[:10] if candles else []}
                return self.normalize(raw_data, "trades")
            
            else:
                raise ValueError(f"Unknown data_type: {data_type}")
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Hyperliquid fetch error: {e}")

    async def fetch_all_markets(self) -> List[Dict[str, Any]]:
        """
        Fetch data for ALL markets.
        """
        try:
            # Use metaAndAssetCtxs to get rich data
            payload = {"type": "metaAndAssetCtxs"}
            response_data = await self.http_client._post(payload)
            
            # Response is [universe, assetCtxs]
            universe = response_data[0]['universe']
            asset_ctxs = response_data[1]
            
            markets = []
            
            for idx, asset in enumerate(universe):
                if idx >= len(asset_ctxs):
                    break
                    
                symbol_name = asset['name']
                # Filter out indices / dead markets
                if symbol_name.startswith("@"):
                    continue
                    
                # Filter out delisted/placeholder assets
                if asset.get('isDelisted', False):
                    continue
                    
                ctx = asset_ctxs[idx]
                symbol = symbol_name + "-USD" # Normalize to X-USD
                
                # Filter out inactive markets (Volume == 0)
                # User reported MKR-USD as delisted (confirmed by volume 0)
                # Note: valid assets like DOGE have szDecimals=0, so do NOT filter by that.
                volume_24h = float(ctx.get('dayNtlVlm') or 0)
                if volume_24h == 0:
                    continue
                
                # Calculate 24h stats
                # Calculate 24h stats with fallback
                current_price = float(ctx.get('midPx') or ctx.get('markPx') or ctx.get('oraclePx') or 0)
                prev_day_price = float(ctx.get('prevDayPx') or 0)
                
                # Only calculate change if we have both prices
                if current_price > 0 and prev_day_price > 0:
                    change_24h = current_price - prev_day_price
                    change_percent_24h = (change_24h / prev_day_price * 100)
                else:
                    change_24h = 0
                    change_percent_24h = 0
                
                # Only add market if it has a price and some activity or valid stats
                if current_price <= 0:
                    continue

                markets.append({
                    "symbol": symbol,
                    "price": current_price,
                    "change_24h": change_24h,
                    "change_percent_24h": change_percent_24h,
                    "volume_24h": float(ctx.get('dayNtlVlm') or 0),
                    "high_24h": None,
                    "low_24h": None,
                    "source": "hyperliquid",
                    "category": get_category(symbol_name)
                })
                
            return markets

        except Exception as e:
            print(f"Hyperliquid fetch_all error: {e}")
            return []
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Subscribe to real-time WebSocket updates.
        
        Args:
            symbol: Trading symbol
            callback: Function to call with new data
            **kwargs: subscription_type ("allMids" | "l2Book" | "trades" | "user")
        """
        subscription_type = kwargs.get("subscription_type", "allMids")
        
        # Register callback
        self._callbacks.append(callback)
        
        # Subscribe via existing WebSocket client
        await self.ws_client.subscribe(
            subscription_type,
            self._handle_ws_message,
            coin=symbol if subscription_type != "user" else None,
            user=kwargs.get("user") if subscription_type == "user" else None
        )
    
    async def _handle_ws_message(self, message: Dict[str, Any]) -> None:
        """Internal: Handle WebSocket message"""
        try:
            normalized = self.normalize(message)
            await self._notify_subscribers(normalized)
        except Exception as e:
            print(f"Error handling WS message: {e}")
    
    def normalize(self, raw_data: Any, data_type: str = "price") -> Dict[str, Any]:
        """
        Normalize Hyperliquid data to standard format.
        
        Args:
            raw_data: Raw data from Hyperliquid API
            data_type: Type of data being normalized
        
        Returns:
            {
                "source": "hyperliquid",
                "symbol": symbol,
                "data_type": type,
                "timestamp": int,
                "data": {...}
            }
        """
        normalized = {
            "source": "hyperliquid",
            "data_type": data_type,
            "timestamp": None,
            "data": {}
        }
        
        if data_type == "price":
            # Normalize price data
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "price": float(raw_data.get("mid", 0)),
                "mark_price": float(raw_data.get("markPx", 0)),
                "index_price": float(raw_data.get("indexPx", raw_data.get("oraclePx", 0))),
                "change_24h": float(raw_data.get("change_24h", 0)),
                "change_percent_24h": float(raw_data.get("change_percent_24h", 0)),
                "volume_24h": float(raw_data.get("volume_24h", 0)),
                "open_interest": float(raw_data.get("open_interest", 0))
            }
        
        elif data_type == "orderbook":
            # Normalize orderbook
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "bids": raw_data.get("levels", [[]])[0],  # [[price, size], ...]
                "asks": raw_data.get("levels", [[], []])[1],
                "timestamp": raw_data.get("time", 0)
            }
        
        elif data_type == "trades":
            # Normalize trades
            normalized["data"] = {
                "trades": raw_data.get("trades", [])
            }
        
        elif data_type == "funding":
            # Normalize funding rate
            normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
            normalized["data"] = {
                "funding_rate": float(raw_data.get("funding", 0)),
                "premium": float(raw_data.get("premium", 0)),
                "next_funding_time": raw_data.get("next_funding_time", 0)
            }
        
        elif data_type == "volume":
             normalized["symbol"] = raw_data.get("coin", "UNKNOWN")
             normalized["data"] = {
                "volume_24h": float(raw_data.get("volume_24h", 0)),
                "volume_base": float(raw_data.get("volume_base", 0))
             }
        
        return normalized

    # ===== Trading Methods =====
    """
    Trading method implementations for Hyperliquid Connector
    """
    
    import time
    from typing import Dict, Any, List
    
    
    # Add to HyperliquidConnector class:
    
    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place order via Hyperliquid Exchange API.
        
        Args:
            user_address: User's wallet address (for session key signing)
            symbol: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', or 'stop_limit'
            size: Order size in base currency
            price: Limit price (required for limit/stop_limit)
            stop_price: Stop trigger price (required for stop_limit)
            **kwargs: Additional params (reduce_only, time_in_force, etc.)
        
        Returns:
            {
                'exchange': 'hyperliquid',
                'exchange_order_id': str,
                'status': str,
                'raw_response': dict
            }
        """
        try:
            # Convert symbol format (BTC-USD → BTC)
            coin = symbol.split('-')[0]
            
            # Build order params
            order_params = {
                "asset": coin,
                "is_buy": side == 'buy',
                "sz": size,
                "reduce_only": kwargs.get('reduce_only', False)
            }
            
            # Add Builder Fee (Hyperliquid Protocol Spec)
            if self.builder_address:
                order_params["f"] = self.builder_fee_tenths
                # Note: 'b' (builder address) is usually passed at the action level 
                # in the SDK, but we store it here for the payload builder.
                order_params["builder"] = self.builder_address 
            
            # Order type specific params
            if order_type == 'market':
                order_params["order_type"] = {"market": {}}
            elif order_type == 'limit':
                if not price:
                    raise ValueError("Limit orders require price")
                order_params["limit_px"] = price
                order_params["order_type"] = {
                    "limit": {
                        "tif": kwargs.get('time_in_force', 'Gtc')  # Good-til-cancel
                    }
                }
            elif order_type == 'stop_limit':
                if not stop_price or not price:
                    raise ValueError("Stop limit orders require both stop_price and price")
                order_params["trigger_px"] = stop_price
                order_params["limit_px"] = price
                order_params["order_type"] = {
                    "trigger": {
                        "tpsl": "sl",
                        "limit_px": price
                    }
                }
            
            # TODO: Sign with user's session key (Phase 2 - Security Enhancement)
            # For now, this is a placeholder - actual signing would require:
            # - User's session key
            # - Proper EIP-712 signature
            # - Vault address (if using smart account)
            
            # Commented out actual API call until session key signing is implemented
            # response = await self.http_client.place_order(order_params)
            
            # Placeholder response for development
            print(f"[Hyperliquid] Would place {side} order for {size} {coin} (type: {order_type})")
            
            return {
                "exchange": "hyperliquid",
                "exchange_order_id": f"hl_test_{symbol}_{int(time.time() * 1000)}",
                "status": "pending",
                "raw_response": {
                    "note": "Placeholder - session key signing not yet implemented",
                    "order_params": order_params
                }
            }
        
        except Exception as e:
            print(f"[Hyperliquid] Error placing order: {e}")
            raise
    
    
    async def cancel_order(
        self,
        user_address: str,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Cancel order on Hyperliquid.
        
        Args:
            user_address: User's wallet address
            order_id: Exchange order ID
        
        Returns:
            {'status': 'cancelled', 'order_id': str}
        """
        try:
            # TODO: Implement with session key signing
            # response = await self.http_client.cancel_order(order_id)
            
            print(f"[Hyperliquid] Would cancel order {order_id}")
            
            return {
                "status": "cancelled",
                "order_id": order_id,
                "note": "Placeholder - session key signing not yet implemented"
            }
        
        except Exception as e:
            print(f"[Hyperliquid] Error cancelling order: {e}")
            raise
    
    
    async def get_user_positions(
        self, 
        user_address: str
    ) -> Dict[str, Any]:
        """
        Get user's active positions from Hyperliquid.
        
        Args:
            user_address: User's wallet address
        
        Returns:
            {
                "positions": List[Dict],
                "summary": Dict
            }
        """
        try:
            payload = {"type": "clearinghouseState", "user": user_address}
            response = await self.http_client._post(payload)
            
            positions = []
            summary = {
                "account_value": 0,
                "total_margin_used": 0,
                "free_collateral": 0,
                "margin_usage": 0,
                "leverage": 0
            }
            
            # Parse summary if available
            margin_summary = response.get('marginSummary', response.get('crossMarginSummary', {}))
            if margin_summary:
                summary["account_value"] = float(margin_summary.get('accountValue', 0))
                summary["total_margin_used"] = float(margin_summary.get('totalMarginUsed', 0))
                summary["free_collateral"] = summary["account_value"] - summary["total_margin_used"]
                if summary["account_value"] > 0:
                    summary["margin_usage"] = (summary["total_margin_used"] / summary["account_value"]) * 100
            
            if 'assetPositions' in response:
                total_notional = 0
                for pos in response['assetPositions']:
                    position_data = pos['position']
                    szi = float(position_data['szi'])
                    entry_px = float(position_data['entryPx'])
                    mark_px = float(position_data.get('markPx', entry_px))
                    
                    notional = abs(szi) * mark_px
                    total_notional += notional
                    
                    positions.append({
                        "symbol": position_data['coin'] + '-USD',
                        "side": 'long' if szi > 0 else 'short',
                        "size": abs(szi),
                        "entry_price": entry_px,
                        "mark_price": mark_px,
                        "unrealized_pnl": float(position_data.get('unrealizedPnl', 0)),
                        "liquidation_price": float(position_data.get('liquidationPx', 0)) if position_data.get('liquidationPx') else None,
                        "leverage": float(position_data.get('leverage', {}).get('value', 1)),
                        "margin_used": float(position_data.get('marginUsed', 0))
                    })
                
                # Calculate aggregate leverage
                if summary["account_value"] > 0:
                    summary["leverage"] = total_notional / summary["account_value"]
            
            return {
                "positions": positions,
                "summary": summary
            }
        
        except Exception as e:
            print(f"[Hyperliquid] Error fetching positions: {e}")
            return {"positions": [], "summary": {}}
    
    
    async def get_user_orders(
        self,
        user_address: str,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get user's orders from Hyperliquid.
        
        Args:
            user_address: User's wallet address
            status: Optional filter ('open', 'filled', 'cancelled')
        
        Returns:
            List of order dicts
        """
        try:
            # Fetch open orders
            payload = {"type": "openOrders", "user": user_address}
            response = await self.http_client._post(payload)
            
            orders = []
            for order in response:
                order_dict = {
                    "id": order.get('oid'),
                    "symbol": order.get('coin') + '-USD',
                    "side": 'buy' if order.get('side') == 'B' else 'sell',
                    "order_type": order.get('orderType', 'limit'),
                    "price": float(order.get('limitPx', 0)),
                    "size": float(order.get('sz', 0)),
                    "filled_size": float(order.get('filledSz', 0)),
                    "status": 'open',
                    "timestamp": order.get('timestamp', 0)
                }
                orders.append(order_dict)
            
            # Filter by status if requested
            if status:
                orders = [o for o in orders if o['status'] == status]
            
            return orders
        
        except Exception as e:
            print(f"[Hyperliquid] Error fetching orders: {e}")
            return []
    
