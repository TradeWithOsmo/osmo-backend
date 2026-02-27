"""
Avantis Exchange API client
Based on official Python SDK: https://github.com/Avantis-Labs/avantis_trader_sdk
Docs: https://sdk.avantisfi.com/

Avantis is on Base chain. Market data comes from:
1. Official SDK (avantis-trader-sdk) — reads on-chain via Base RPC
2. Pyth/Lazer price feeds (SSE streams)
3. The Graph subgraph (graphQL)
4. Official REST endpoint (if available)

SDK install: pip install avantis-trader-sdk
"""
import httpx
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

AVANTIS_SUBGRAPH = "https://api.studio.thegraph.com/query/49377/avantis-base/version/latest"
AVANTIS_BASE_RPC = "https://mainnet.base.org"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_s: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_s = timeout_s
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False

    def record_success(self):
        self.failures = 0
        self.is_open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.is_open = True
            logger.warning(f"[Avantis] Circuit breaker OPEN after {self.failures} failures")

    def can_attempt(self) -> bool:
        if not self.is_open:
            return True
        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.timeout_s:
                self.is_open = False
                self.failures = 0
                return True
        return False


class AvantisAPIClient:
    """
    HTTP client for Avantis (Base chain).
    Preferred: avantis-trader-sdk (on-chain reads)
    Fallback: GraphQL subgraph
    """

    _SDK_PAIRS_CACHE: Optional[List[Dict]] = None  # class-level cache

    def __init__(self, rpc_url: str = AVANTIS_BASE_RPC):
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=15.0, verify=False)
        self.circuit_breaker = CircuitBreaker()
        self.last_successful_fetch: Optional[datetime] = None
        self._sdk_available = self._check_sdk()

    def _check_sdk(self) -> bool:
        try:
            import avantis_trader_sdk  # noqa
            return True
        except ImportError:
            return False

    async def _fetch_pairs_sdk(self) -> Optional[List[Dict]]:
        """
        Use avantis-trader-sdk to get all pairs from on-chain.
        await trader_client.pairs_cache.get_pairs_info()
        Returns {index: PairInfo} where PairInfo has .from_ and .to
        """
        if not self._sdk_available:
            return None
        try:
            from avantis_trader_sdk import TraderClient
            trader_client = TraderClient(self.rpc_url)
            pairs_info = await trader_client.pairs_cache.get_pairs_info()
            results = []
            for idx, pair in pairs_info.items():
                from_sym = (getattr(pair, "from_", None) or getattr(pair, "from", None) or "").upper()
                to_sym = (getattr(pair, "to", None) or "USD").upper()
                if not from_sym:
                    continue
                results.append({
                    "pair_index": idx,
                    "from": from_sym,
                    "to": to_sym,
                    "symbol": f"{from_sym}-{to_sym}",
                    "source": "avantis_sdk",
                })
            logger.info(f"[Avantis] SDK: {len(results)} pairs ✓")
            return results
        except Exception as e:
            logger.debug(f"[Avantis] SDK fetch failed: {e}")
            return None

    async def _fetch_pairs_subgraph(self) -> Optional[List[Dict]]:
        """Fallback: fetch pairs from The Graph subgraph."""
        query = '{ pairs(first: 100, where: {isActive: true}) { pairIndex from to } }'
        try:
            resp = await self.client.post(
                AVANTIS_SUBGRAPH,
                json={"query": query},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            pairs = data.get("data", {}).get("pairs", [])
            if not pairs:
                return None
            results = []
            for p in pairs:
                from_sym = p.get("from", "").upper()
                to_sym = p.get("to", "USD").upper()
                if not from_sym:
                    continue
                results.append({
                    "pair_index": p.get("pairIndex"),
                    "from": from_sym,
                    "to": to_sym,
                    "symbol": f"{from_sym}-{to_sym}",
                    "source": "avantis_subgraph",
                })
            logger.info(f"[Avantis] Subgraph: {len(results)} pairs ✓")
            return results
        except Exception as e:
            logger.debug(f"[Avantis] Subgraph failed: {e}")
            return None

    async def get_latest_prices(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all Avantis markets. Price data from Pyth/on-chain is not
        available via simple REST — returns pairs with metadata only.
        Price updates come via Pyth SSE stream.
        """
        if not self.circuit_breaker.can_attempt():
            return None

        # Try SDK first, then subgraph
        pairs = await self._fetch_pairs_sdk()
        if not pairs:
            pairs = await self._fetch_pairs_subgraph()

        if not pairs:
            self.circuit_breaker.record_failure()
            return None

        results = []
        for p in pairs:
            results.append({
                "symbol": p["symbol"],
                "tradingSymbol": p["symbol"],
                "from": p["from"],
                "to": p["to"],
                "price": None,   # price comes from Pyth feeds, not REST
                "pair_index": p.get("pair_index"),
                "max_leverage": 50,  # Avantis default max leverage
                "source": "avantis",
            })

        self.circuit_breaker.record_success()
        self.last_successful_fetch = datetime.now()
        return results

    async def get_markets(self) -> List[Dict[str, Any]]:
        return await self.get_latest_prices() or []

    def get_status(self) -> dict:
        return {
            "exchange": "avantis",
            "chain": "base",
            "sdk_available": self._sdk_available,
            "rpc_url": self.rpc_url,
            "circuit_breaker_open": self.circuit_breaker.is_open,
            "failures": self.circuit_breaker.failures,
            "last_successful_fetch": self.last_successful_fetch.isoformat() if self.last_successful_fetch else None,
        }

    async def close(self):
        await self.client.aclose()
