import asyncio
import logging
from typing import Dict, List
from config import settings
from connectors.web3_arbitrum.connector import web3_connector

logger = logging.getLogger(__name__)

class PricePusher:
    """
    Pushes aggregated market prices from Hyperliquid and Ostium to the on-chain OrderRouter.
    This fulfills the requirement of being a perp aggregator with its own oracle.
    """
    
    def __init__(self):
        self.running = False
        self.update_interval = 10  # Push prices every 10 seconds (adjust for gas/needs)
        self.major_symbols = [
            "BTC-USD", "ETH-USD", "SOL-USD", "ARB-USD", 
            "GOLD", "SILVER", "OIL", "EURUSD"
        ]
        self.router_contract = None
        self.account = None

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

    async def _push_prices(self, latest_prices: Dict[str, dict], connected_clients: Dict[str, set] = None):
        # 1. Initialize contract if needed
        if not self.router_contract:
            try:
                self.router_contract = web3_connector.get_contract("OrderRouter")
                self.account = web3_connector.account
            except Exception as e:
                logger.error(f"Failed to initialize OrderRouter for PricePusher: {e}")
                return

        if not self.account:
            logger.warning("No Treasury Account loaded, cannot push prices.")
            return

        # 2. Identify ACTIVE symbols (those with open positions, pending orders, OR active viewers)
        # This optimization saves gas by only pushing prices for pairs being traded or viewed.
        active_symbols = set()
        
        # A. Add Viewed symbols (from WebSocket subscribers in main.py)
        if connected_clients:
            for symbol in connected_clients.keys():
                if symbol != "ALL": # Skip global stream
                    active_symbols.add(symbol)

        try:
            from database.connection import AsyncSessionLocal
            from database.models import Position, Order
            from sqlalchemy import select, or_
            
            async with AsyncSessionLocal() as session:
                # B. Get symbols from active positions
                pos_stmt = select(Position.symbol).where(Position.size > 0)
                pos_res = await session.execute(pos_stmt)
                for row in pos_res:
                    active_symbols.add(row[0])
                
                # C. Get symbols from pending orders
                ord_stmt = select(Order.symbol).where(Order.status == 'pending')
                ord_res = await session.execute(ord_stmt)
                for row in ord_res:
                    active_symbols.add(row[0])
                    

            if not active_symbols:
                # logger.debug("No active symbols to push.")
                return
        except Exception as e:
            logger.error(f"Error fetching active symbols for PricePusher: {e}")
            # If DB fails, we still have viewed symbols from (A)
            if not active_symbols:
                return

        # 3. Collect prices for ACTIVE symbols only
        symbols_to_push = []
        prices_to_push = []
        
        for symbol in active_symbols:
            if symbol in latest_prices:
                price_data = latest_prices[symbol]
                price = price_data.get("price")
                if price is not None:
                    symbols_to_push.append(symbol)
                    # Convert to 1e6 (Contract precision)
                    prices_to_push.append(int(float(price) * 1e6))

        if not symbols_to_push:
            return

        # 4. Transact in Batches
        batch_size = 30
        w3 = web3_connector.w3
        
        for i in range(0, len(symbols_to_push), batch_size):
            batch_symbols = symbols_to_push[i:i+batch_size]
            batch_prices = prices_to_push[i:i+batch_size]
            
            try:
                nonce = w3.eth.get_transaction_count(self.account.address, 'pending')
                
                txn = self.router_contract.functions.updatePrices(
                    batch_symbols, 
                    batch_prices
                ).build_transaction({
                    'from': self.account.address,
                    'nonce': nonce,
                    'gas': 800000,
                    'gasPrice': int(w3.eth.gas_price * 1.2),
                    'chainId': settings.CHAIN_ID
                })
                
                signed_txn = w3.eth.account.sign_transaction(txn, settings.TREASURY_PRIVATE_KEY)
                tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                
                logger.info(f"🚀 [DynamicOracle] Pushed {len(batch_symbols)} active prices. Tx: {tx_hash.hex()}")
                
                if i + batch_size < len(symbols_to_push):
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Failed to push active price batch starting at {i}: {e}")

price_pusher = PricePusher()
