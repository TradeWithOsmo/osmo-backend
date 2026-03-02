import asyncio
import logging
from typing import Dict, List, Optional
from config import settings
from connectors.web3_arbitrum.connector import web3_connector

logger = logging.getLogger(__name__)

# Funding rate scale: Hyperliquid reports hourly funding as a decimal (e.g. 0.0001).
# Contract stores it as integer bps*1e4 for sub-bps precision.
# 1 bps = 0.0001 → multiply by 1_000_000 to get 1e-10 resolution (int256 safe).
_FUNDING_SCALE = 1_000_000


class PricePusher:
    """
    Pushes aggregated market prices and funding data to on-chain contracts:
      1. OrderRouter.updatePrices()         — price oracle used for order execution
      2. CustomMarketDataFeed.updateMarketDataBatch() — extended feed (price + fundingRate + basis)
    """

    def __init__(self):
        self.running = False
        self.update_interval = 10  # seconds
        self.router_contract = None
        self.feed_contract = None
        self.account = None
        self._feed_role_ok: Optional[bool] = None  # cached role check result

    async def start(self, latest_prices: Dict[str, dict], connected_clients: Dict[str, set] = None):
        if self.running:
            return
        self.running = True
        asyncio.create_task(self._run_loop(latest_prices, connected_clients))
        logger.info("🚀 PricePusher started")

    async def stop(self):
        self.running = False
        logger.info("🛑 PricePusher stopped")

    async def _run_loop(self, latest_prices: Dict[str, dict], connected_clients: Dict[str, set] = None):
        while self.running:
            try:
                await self._push_prices(latest_prices, connected_clients)
            except Exception as e:
                logger.error(f"Error pushing prices: {e}")
            await asyncio.sleep(self.update_interval)

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_contracts(self) -> bool:
        """Load contracts on first use. Returns True if OrderRouter is ready."""
        if not self.router_contract:
            try:
                self.router_contract = web3_connector.get_contract("OrderRouter")
                self.account = web3_connector.account
            except Exception as e:
                logger.error(f"Failed to initialise OrderRouter for PricePusher: {e}")
                return False

        if not self.feed_contract:
            try:
                self.feed_contract = web3_connector.get_contract("CustomMarketDataFeed")
                logger.info("✅ CustomMarketDataFeed contract loaded")
                self._verify_updater_role()
            except Exception as e:
                logger.warning(f"CustomMarketDataFeed not available (push will be skipped): {e}")

        return True

    def _verify_updater_role(self):
        """Check once that treasury has DATA_UPDATER_ROLE on CustomMarketDataFeed."""
        if self._feed_role_ok is not None or not self.feed_contract or not self.account:
            return
        try:
            role = self.feed_contract.functions.DATA_UPDATER_ROLE().call()
            has_role = self.feed_contract.functions.hasRole(role, self.account.address).call()
            self._feed_role_ok = has_role
            if has_role:
                logger.info(f"✅ Treasury {self.account.address} has DATA_UPDATER_ROLE on CustomMarketDataFeed")
            else:
                logger.warning(
                    f"⚠️  Treasury {self.account.address} is missing DATA_UPDATER_ROLE on CustomMarketDataFeed "
                    f"(0x3044C64982874dC3401428F4e3eed96976bb4131). "
                    f"Run: grantRole(DATA_UPDATER_ROLE, {self.account.address})"
                )
        except Exception as e:
            logger.warning(f"Could not verify DATA_UPDATER_ROLE: {e}")
            self._feed_role_ok = False

    # ------------------------------------------------------------------
    # Core push logic
    # ------------------------------------------------------------------

    async def _push_prices(self, latest_prices: Dict[str, dict], connected_clients: Dict[str, set] = None):
        if not self._init_contracts():
            return

        if not self.account:
            logger.warning("No Treasury Account loaded, cannot push prices.")
            return

        # 1. Collect active symbols (viewed + open positions + pending orders)
        active_symbols = set()

        if connected_clients:
            for sym in connected_clients.keys():
                if sym != "ALL":
                    active_symbols.add(sym)

        try:
            from database.connection import AsyncSessionLocal
            from database.models import Position, Order
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                pos_res = await session.execute(select(Position.symbol).where(Position.size > 0))
                for row in pos_res:
                    active_symbols.add(row[0])

                ord_res = await session.execute(select(Order.symbol).where(Order.status == 'pending'))
                for row in ord_res:
                    active_symbols.add(row[0])

            if not active_symbols:
                return
        except Exception as e:
            logger.error(f"Error fetching active symbols for PricePusher: {e}")
            if not active_symbols:
                return

        # 2. Build payload arrays
        symbols_to_push: List[str] = []
        prices_1e6:      List[int] = []
        funding_bps:     List[int] = []  # int256 — scaled by _FUNDING_SCALE
        basis_bps:       List[int] = []  # int256 — 0 until we have a basis source

        for sym in active_symbols:
            if sym not in latest_prices:
                continue
            data = latest_prices[sym]
            price = data.get("price")
            if price is None:
                continue

            raw_funding = data.get("funding_rate") or data.get("fundingRate") or 0
            symbols_to_push.append(sym)
            prices_1e6.append(int(float(price) * 1e6))
            funding_bps.append(int(float(raw_funding) * _FUNDING_SCALE))
            basis_bps.append(0)  # placeholder — update when basis source is available

        if not symbols_to_push:
            return

        w3 = web3_connector.w3
        batch_size = 30

        # 3. Push to OrderRouter
        await self._push_to_order_router(w3, symbols_to_push, prices_1e6, batch_size)

        # 4. Push to CustomMarketDataFeed (if contract loaded + role ok)
        if self.feed_contract and self._feed_role_ok:
            await self._push_to_feed(w3, symbols_to_push, prices_1e6, funding_bps, basis_bps, batch_size)

    async def _push_to_order_router(self, w3, symbols: List[str], prices: List[int], batch_size: int):
        for i in range(0, len(symbols), batch_size):
            bs = symbols[i:i + batch_size]
            bp = prices[i:i + batch_size]
            try:
                nonce = w3.eth.get_transaction_count(self.account.address, 'pending')
                txn = self.router_contract.functions.updatePrices(bs, bp).build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                    'gas': 800_000,
                    'gasPrice': int(w3.eth.gas_price * 1.2),
                    'chainId': settings.CHAIN_ID,
                })
                signed = w3.eth.account.sign_transaction(txn, settings.TREASURY_PRIVATE_KEY)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                logger.info(f"📡 [OrderRouter] Pushed {len(bs)} prices. Tx: {tx_hash.hex()}")
                if i + batch_size < len(symbols):
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[OrderRouter] Failed batch at {i}: {e}")

    async def _push_to_feed(
        self, w3,
        symbols: List[str], prices: List[int],
        funding: List[int], basis: List[int],
        batch_size: int,
    ):
        for i in range(0, len(symbols), batch_size):
            bs  = symbols[i:i + batch_size]
            bp  = prices[i:i + batch_size]
            bfr = funding[i:i + batch_size]
            bba = basis[i:i + batch_size]
            try:
                nonce = w3.eth.get_transaction_count(self.account.address, 'pending')
                txn = self.feed_contract.functions.updateMarketDataBatch(
                    bs, bp, bfr, bba
                ).build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                    'gas': 1_000_000,
                    'gasPrice': int(w3.eth.gas_price * 1.2),
                    'chainId': settings.CHAIN_ID,
                })
                signed = w3.eth.account.sign_transaction(txn, settings.TREASURY_PRIVATE_KEY)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                logger.info(f"📊 [CustomFeed] Pushed {len(bs)} symbols (price+funding+basis). Tx: {tx_hash.hex()}")
                if i + batch_size < len(symbols):
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[CustomFeed] Failed batch at {i}: {e}")


price_pusher = PricePusher()
