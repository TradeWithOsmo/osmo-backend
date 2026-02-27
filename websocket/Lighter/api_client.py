"""
Lighter Exchange API client
Uses the official `lighter-sdk` Python package to fetch market info.
Endpoint: uses SDK's default mainnet host (https://mainnet.zklighter.elliot.ai)
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class LighterAPIClient:
    """
    Client for Lighter Exchange (ZK L2 Arbitrum).
    Uses the official `lighter-sdk` package to enumerate markets.
    """

    def __init__(self):
        self.last_successful_fetch: Optional[datetime] = None
        self._sdk_available = self._check_sdk()
        self._market_id_map: Dict[str, int] = {}  # "BTC-USD" -> market_id

    @staticmethod
    def _lookup_keys(symbol: str) -> List[str]:
        raw = str(symbol or "").strip().upper().replace("/", "-").replace("_", "-")
        if not raw:
            return []
        compact = raw.replace("-", "")
        keys = [raw, compact]
        if raw.endswith("-LIGHTER"):
            keys.append(raw.replace("-LIGHTER", "-USD"))
        if raw.endswith("-PERP"):
            keys.append(raw.replace("-PERP", "-USD"))
        if "-" in raw:
            base, quote = (raw.split("-", 1) + ["USD"])[:2]
            keys.append(f"{base}-{quote}")
            keys.append(f"{base}{quote}")
        # Keep order, remove duplicates
        seen = set()
        unique: List[str] = []
        for k in keys:
            if k and k not in seen:
                unique.append(k)
                seen.add(k)
        return unique

    def _resolve_market_id(self, symbol: str) -> Optional[int]:
        for key in self._lookup_keys(symbol):
            market_id = self._market_id_map.get(key)
            if market_id is not None:
                return market_id
        return None

    def _check_sdk(self) -> bool:
        try:
            import lighter  # noqa
            return True
        except ImportError:
            logger.warning("[Lighter] lighter-sdk not installed. Run: pip install lighter-sdk")
            return False

    async def get_markets_via_sdk(self) -> List[Dict]:
        from lighter import ApiClient, OrderApi

        api_client = ApiClient()
        try:
            order_api = OrderApi(api_client)
            resp = await order_api.order_books()
            books = resp.order_books if hasattr(resp, "order_books") else []
            results = []
            for book in books:
                d = book.dict() if hasattr(book, "dict") else book.__dict__
                status = d.get("status", "active")
                if status != "active":
                    continue
                symbol_raw = d.get("symbol", "")
                market_id = d.get("market_id")
                market_type = d.get("market_type", "perp")

                if not symbol_raw:
                    continue

                base = symbol_raw.upper()
                quote = "USD"
                unified_symbol = f"{base}-{quote}"
                
                # Store mapping for depth/trades lookups
                self._market_id_map[unified_symbol] = market_id
                self._market_id_map[f"{base}-LIGHTER"] = market_id
                self._market_id_map[base] = market_id

                results.append({
                    "symbol": unified_symbol,
                    "tradingSymbol": f"{base}-LIGHTER",
                    "from": base,
                    "to": quote,
                    "price": 0.0,
                    "source": "lighter",
                    "market_id": market_id,
                    "market_type": market_type,
                })
            logger.info(f"[Lighter] SDK fetched {len(results)} active markets")
            return results
        except Exception as e:
            logger.warning(f"[Lighter] SDK fetch failed: {e}")
            return []
        finally:
            await api_client.close()

    async def get_markets(self) -> List[Dict[str, Any]]:
        """Return list of Lighter markets."""
        results = []
        if self._sdk_available:
            results = await self.get_markets_via_sdk()
        
        if not results:
            logger.warning("[Lighter] SDK failed or unavailable. Using known market fallbacks.")
            known_lighter = [("WETH", 0), ("WBTC", 1), ("ARB", 2), ("EZETH", 3), ("WEETH", 4), ("USDCE", 5)]
            for base, m_id in known_lighter:
                base_clean = base.upper().replace("USDC", "").replace("-", "")
                unified_symbol = f"{base_clean}-USD"
                
                self._market_id_map[unified_symbol] = m_id
                self._market_id_map[f"{base_clean}-LIGHTER"] = m_id
                self._market_id_map[base_clean] = m_id
                
                results.append({
                    "symbol": unified_symbol,
                    "tradingSymbol": f"{base_clean}-LIGHTER",
                    "from": base_clean,
                    "to": "USD",
                    "price": 0.0,
                    "source": "lighter",
                    "market_id": m_id,
                    "market_type": "perp",
                })
        
        if results:
            self.last_successful_fetch = datetime.now()
        return results

    async def get_depth(self, symbol: str) -> Optional[Dict]:
        """Fetch orderbook for a symbol via SDK.

        The Lighter SDK `order_book_details` response may vary between SDK versions:
        - Top-level: `resp.bids` / `resp.asks`  (no nesting)
        - Nested:    `resp.order_book.bids` / `resp.order_book.asks`
        Level items use `limit_price` / `amount` field names (NOT `px` / `sz`).
        We normalise to {px, sz} here so the WS handler's `_extract_price_size` always works.
        """
        if not self._sdk_available:
            return None

        market_id = self._resolve_market_id(symbol)
        if market_id is None:
            # Populate the market map on first use (cold-start)
            await self.get_markets()
            market_id = self._resolve_market_id(symbol)

        if market_id is None:
            return None

        from lighter import ApiClient, OrderApi
        api_client = ApiClient()
        try:
            order_api = OrderApi(api_client)
            resp = await order_api.order_book_details(market_id=market_id)
            d = resp.dict() if hasattr(resp, "dict") else resp.__dict__

            # Prefer flat layout; fall back to nested `order_book` key
            if "bids" in d or "asks" in d:
                raw_bids = d.get("bids", []) or []
                raw_asks = d.get("asks", []) or []
            else:
                ob = d.get("order_book") or {}
                if hasattr(ob, "dict"):
                    ob = ob.dict()
                elif hasattr(ob, "__dict__"):
                    ob = ob.__dict__
                raw_bids = ob.get("bids", []) or []
                raw_asks = ob.get("asks", []) or []

            def _to_level(lv) -> Dict:
                """Convert SDK level object/dict to {'px': str, 'sz': str}."""
                if hasattr(lv, "dict"):
                    lv = lv.dict()
                elif hasattr(lv, "__dict__"):
                    lv = lv.__dict__
                if not isinstance(lv, dict):
                    return {}
                price = (
                    lv.get("limit_price")
                    or lv.get("price")
                    or lv.get("px")
                    or lv.get("p")
                    or 0
                )
                size = (
                    lv.get("amount")
                    or lv.get("base_amount")
                    or lv.get("size")
                    or lv.get("sz")
                    or lv.get("qty")
                    or 0
                )
                return {"px": str(price), "sz": str(size)}

            bids = [_to_level(b) for b in raw_bids]
            asks = [_to_level(a) for a in raw_asks]

            return {
                "bids": bids,
                "asks": asks,
            }
        except Exception as e:
            logger.debug(f"[Lighter] get_depth failed for {symbol}: {e}")
            return None
        finally:
            await api_client.close()

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> Optional[List]:
        """Fetch recent trades for a symbol via SDK."""
        if not self._sdk_available:
            return None
            
        market_id = self._resolve_market_id(symbol)
        if market_id is None:
            await self.get_markets()
            market_id = self._resolve_market_id(symbol)
        if market_id is None:
            return None

        from lighter import ApiClient, OrderApi
        api_client = ApiClient()
        try:
            order_api = OrderApi(api_client)
            resp = await order_api.recent_trades(market_id=market_id, limit=limit)
            trades = resp.trades if hasattr(resp, "trades") else []
            return [t.dict() if hasattr(t, "dict") else t.__dict__ for t in trades]
        except Exception as e:
            logger.debug(f"[Lighter] get_recent_trades failed for {symbol}: {e}")
            return None
        finally:
            await api_client.close()

    def get_status(self) -> dict:
        return {
            "exchange": "lighter",
            "chain": "arbitrum",
            "sdk_available": self._sdk_available,
            "last_successful_fetch": (
                self.last_successful_fetch.isoformat()
                if self.last_successful_fetch else None
            ),
        }
