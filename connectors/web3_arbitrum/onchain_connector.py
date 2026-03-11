import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from web3 import Web3

from connectors.base_connector import BaseConnector, ConnectorStatus
from connectors.web3_arbitrum.connector import web3_connector
from connectors.web3_arbitrum.session_manager import session_manager
try:
    from backend.websocket.config import settings
except ImportError:
    try:
        from websocket.config import settings
    except ImportError:
        from config import settings

logger = logging.getLogger(__name__)

class OnchainConnector(BaseConnector):
    """
    Connector for On-Chain Trading via OrderRouter smart contract.
    """
    
    # Crypto symbols for asset type detection
    CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX', 'MATIC', 'ARB', 'DOGE', 'ATOM', 'XRP', 'ADA', 'DOT']
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("onchain", config)
        self.w3_connector = web3_connector
        self.status = ConnectorStatus.HEALTHY if self.w3_connector.initialized else ConnectorStatus.OFFLINE
        self._backup_w3 = None
        self._block_cache = {} # Cache block timestamps to avoid redundant RPC calls
    
    def _detect_asset_type(self, symbol: str) -> str:
        """Detect if symbol is crypto or RWA based on symbol name."""
        base_symbol = symbol.split('-')[0].upper() if '-' in symbol else symbol.upper()
        return 'crypto' if base_symbol in self.CRYPTO_SYMBOLS else 'rwa'
    
    async def _get_current_price(self, symbol: str) -> float:
        """
        Fetch current price from Hyperliquid (crypto) or Ostium (RWA) connector.
        """
        try:
            from connectors.init_connectors import connector_registry
            
            asset_type = self._detect_asset_type(symbol)
            base_symbol = symbol.split('-')[0] if '-' in symbol else symbol
            
            if asset_type == 'crypto':
                connector = connector_registry.get_connector('hyperliquid')
                if connector:
                    result = await connector.fetch(base_symbol, data_type='price')
                    return float(result.get('data', {}).get('price', 0))
            else:
                connector = connector_registry.get_connector('ostium')
                if connector:
                    result = await connector.fetch(base_symbol, data_type='price')
                    return float(result.get('data', {}).get('price', 0))
            
            return 0
        except Exception as e:
            logger.warning(f"Failed to fetch price for {symbol}: {e}")
            return 0
    
    def _calculate_pnl(self, side: str, size_usd: float, entry_price: float, current_price: float) -> float:
        """Calculate unrealized PnL."""
        if entry_price == 0 or current_price == 0:
            return 0
        
        price_diff = current_price - entry_price
        if side == 'sell':  # Short position
            price_diff = -price_diff
        
        # PnL = (price_diff / entry_price) * size_usd
        return (price_diff / entry_price) * size_usd

    async def _push_price_now(self, symbol: str):
        """
        Just-In-Time price push to OrderRouter.
        Ensures the contract has a valid price before placeOrder is called.
        """
        try:
            price = await self._get_current_price(symbol)
            if price <= 0:
                logger.warning(f"Skipping JIT push for {symbol}: Price is 0")
                return

            router = self.w3_connector.get_contract("OrderRouter")
            # Treasury account from connector
            treasury_account = self.w3_connector.account
            if not treasury_account:
                logger.error("No Treasury account available for JIT push")
                return

            price_int = int(price * 1_000_000)
            
            logger.info(f"⏳ [JIT-Oracle] Pushing {symbol} price: {price} to on-chain...")
            
            # Send transaction
            nonce = await asyncio.to_thread(self.w3_connector.w3.eth.get_transaction_count, treasury_account.address, 'pending')
            
            txn = await asyncio.to_thread(
                router.functions.updatePrices([symbol], [price_int]).build_transaction,
                {
                    'from': treasury_account.address,
                    'nonce': nonce,
                    'gas': 300000,
                    'chainId': settings.CHAIN_ID
                }
            )
            
            signed_txn = self.w3_connector.w3.eth.account.sign_transaction(txn, settings.TREASURY_PRIVATE_KEY)
            raw_tx = getattr(signed_txn, "raw_transaction", getattr(signed_txn, "rawTransaction", None))
            tx_hash = await asyncio.to_thread(self.w3_connector.w3.eth.send_raw_transaction, raw_tx)
            
            logger.info(f"✅ [JIT-Oracle] Price pushed! Tx: {tx_hash.hex()}. Waiting for inclusion...")
            
            # We don't necessarily have to wait for full confirmation if the next trade txn 
            # is sent to the same mempool/sequencer and has correct nonces, 
            # but for a hackathon, waiting 1-2 seconds is safer.
            await asyncio.sleep(2) 
            
        except Exception as e:
            logger.error(f"JIT Price Push failed for {symbol}: {e}")
            # We don't raise here, we attempt the trade anyway as it might have a semi-fresh price already

    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch on-chain price or data.
        """
        price = await self._get_current_price(symbol)
        return {
            "status": "success",
            "data": {
                "price": price,
                "symbol": symbol
            }
        }

    async def subscribe(self, symbol: str, callback, **kwargs) -> None:
        """
        Subscribe to on-chain events (OrderExecuted, etc).
        Ideally handled by a dedicated EventMonitor service, but could hook here.
        """
        pass

    def normalize(self, raw_data: Any) -> Dict[str, Any]:
        return raw_data

    async def place_order(
        self,
        user_address: str,
        symbol: str,
        side: str,  # 'buy' | 'sell'
        order_type: str,  # 'market' | 'limit' | 'stop_limit'
        size: float, 
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place order via OrderRouter contract using Session Key.
        Includes Just-In-Time price push for reliability.
        """
        try:
            # 0. JIT Price Push (Ensure oracle is fresh)
            await self._push_price_now(symbol)

            # 1. Get Session Key
            session_key = await session_manager.get_session_key(user_address)
            if not session_key:
                raise ValueError(f"No active session key found for {user_address}")
            
            # 2. Get Contract
            order_router = self.w3_connector.get_contract("OrderRouter")
            
            # 3. Prepare Params
            # struct OrderParams {
            #     address user;
            #     string symbol;
            #     enum Side side;
            #     enum OrderType orderType;
            #     uint256 amountUsd;
            #     uint8 leverage;
            #     uint256 price;
            #     uint256 stopPrice;
            # }
            
            # Enums mapping (from OsmoTypes.sol / consistency)
            # Side: 0=BUY, 1=SELL
            side_enum = 0 if side.lower() == 'buy' else 1
            
            # OrderType in contracts: MARKET=0, LIMIT=1, STOP=2 (see OsmoTypes.sol)
            ot_norm = (order_type or "").strip().lower().replace(" ", "_")
            order_type_map = {
                "market": 0,
                "limit": 1,
                "stop": 2,
                "stop_limit": 2,
                "stop_market": 2,
            }
            order_type_enum = order_type_map.get(ot_norm, 0)
            
            # Decimals handling
            # amountUsd is usually 18 or 6 decimals? USDC is 6.
            # Contracts usually expect Wei or similar.
            # Assume 18 decimals for internal accounting or 6 for USDC?
            # Creating a safe assumption: 1e18 for standard values unless USDC specific.
            # TradingVault normally holds USDC (6 decimals).
            # OrderRouter likely expects values in 1e18 or 1e6.
            # Let's check TradingVault.json later. Assuming 1e18 for "Price" and "Amount" in robust systems,
            # BUT if it transfers USDC, it might need 1e6.
            # Checking `OrderRouter.sol` logic via previous `view_file` might be hard since it was compiled.
            # Price is 1e6 as per PositionManager.sol and frontend
            usd_decimals = 1_000_000 # 6 decimals
            price_decimals = 1_000_000 # 6 decimals
            
            amount_usd_int = int(size * usd_decimals) # Interpreting 'size' as AmountUSD
            price_int = int(price * price_decimals) if price else 0
            stop_price_int = int(stop_price * price_decimals) if stop_price else 0
            leverage = int(kwargs.get('leverage', 1))
            
            # New fields
            reduce_only = bool(kwargs.get('reduce_only', False))
            post_only = bool(kwargs.get('post_only', False))
            
            # Map trigger condition strings to integers (OsmoTypes.TriggerCondition: ABOVE=0, BELOW=1)
            tc_raw = kwargs.get('trigger_condition', 0)
            if isinstance(tc_raw, str):
                tc_map = {'above': 0, 'below': 1, 'none': 0}
                trigger_condition = tc_map.get(tc_raw.strip().lower(), 0)
            else:
                trigger_condition = int(tc_raw or 0)

            tif_raw = kwargs.get('time_in_force', 0)
            if isinstance(tif_raw, str):
                # Contract currently treats timeInForce as 0=GTC, >0=expiry timestamp.
                s = tif_raw.strip().lower().replace(" ", "_")
                if s.isdigit():
                    time_in_force = int(s)
                else:
                    tif_map = {
                        'gtc': 0,
                        'good_til_cancelled': 0,
                        'good_til_date': 0,
                        'ioc': 0,  # Not supported onchain today; treat as GTC
                        'immediate_or_cancel': 0,
                        'fok': 0,  # Not supported onchain today; treat as GTC
                        'fill_or_kill': 0,
                    }
                    time_in_force = tif_map.get(s, 0)
            else:
                time_in_force = int(tif_raw or 0)
            
            params = {
                "user": Web3.to_checksum_address(user_address),
                "symbol": symbol,
                "side": side_enum,
                "orderType": order_type_enum,
                "amountUsd": amount_usd_int,
                "leverage": leverage,
                "reduceOnly": reduce_only,
                "postOnly": post_only,
                "triggerCondition": trigger_condition,
                "price": price_int,
                "stopPrice": stop_price_int,
                "timeInForce": time_in_force
            }
            
            # 4. Build Transaction
            # We need the address of the SESSION KEY that is signing, NOT the user.
            # The transaction is sent FROM the session key.
            # The OrderRouter.placeOrder checks if msg.sender is a valid session key for params.user
            
            from eth_account import Account
            session_account = Account.from_key(session_key)
            session_address = session_account.address
            
            logger.info(f"[OnchainConnector] Nonce check for {session_address}...")
            nonce = await asyncio.to_thread(self.w3_connector.w3.eth.get_transaction_count, session_address, 'pending')

            logger.info(f"[OnchainConnector] Building transaction for {session_address}...")
            def build_tx():
                return order_router.functions.placeOrder(params).build_transaction({
                    'from': session_address,
                    'nonce': nonce,
                    'gas': 2000000,
                    'chainId': settings.CHAIN_ID
                })

            tx_data = await asyncio.to_thread(build_tx)

            # 5. Sign Transaction
            logger.info(f"[OnchainConnector] Signing transaction...")
            signed_tx = await asyncio.to_thread(Account.sign_transaction, tx_data, session_key)

            # 6. Send Transaction
            logger.info(f"[OnchainConnector] Sending raw transaction...")
            raw_tx = getattr(signed_tx, "raw_transaction", getattr(signed_tx, "rawTransaction", None))
            tx_hash = await asyncio.to_thread(self.w3_connector.w3.eth.send_raw_transaction, raw_tx)
            tx_hash_hex = tx_hash.hex()

            logger.info(f"[OnchainConnector] Tx sent: {tx_hash_hex}. Waiting for receipt...")

            # 7. Wait for receipt and extract on-chain orderId
            receipt = await asyncio.to_thread(
                self.w3_connector.w3.eth.wait_for_transaction_receipt, tx_hash, 30
            )

            if receipt['status'] == 0:
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            # Extract orderId from OrderExecuted event (market orders) or OstiumOrderPlaced (limit/stop)
            on_chain_order_id = None
            try:
                executed_logs = order_router.events.OrderExecuted().process_receipt(receipt)
                if executed_logs:
                    on_chain_order_id = executed_logs[0]['args']['orderId'].hex()
            except Exception:
                pass

            if not on_chain_order_id:
                try:
                    placed_logs = order_router.events.OstiumOrderPlaced().process_receipt(receipt)
                    if placed_logs:
                        on_chain_order_id = placed_logs[0]['args']['orderId'].hex()
                except Exception:
                    pass

            order_status = "filled" if on_chain_order_id and order_type_enum == 0 else "pending"
            logger.info(f"[OnchainConnector] Order confirmed! orderId: {on_chain_order_id}, status: {order_status}")

            return {
                "exchange": "onchain",
                "exchange_order_id": on_chain_order_id or tx_hash_hex,
                "status": order_status,
                "raw_response": {"tx_hash": tx_hash_hex, "order_id": on_chain_order_id}
            }
            
        except Exception as e:
            logger.error(f"Failed to place on-chain order: {e}", exc_info=True)
            raise e

    async def cancel_order(self, user_address: str, order_id: str) -> Dict[str, Any]:
        """
        Cancel on-chain order.
        """
        try:
            # 1. Get Session Key
            session_key = await session_manager.get_session_key(user_address)
            if not session_key:
                raise ValueError("No session key")
                
            # 2. Get Contract
            order_router = self.w3_connector.get_contract("OrderRouter")
            
            # 3. Build Tx
            # cancelOrder(address user, bytes32 orderId)
            # msg.sender must be session key
            
            # Convert order_id (str) to bytes32? 
            # If order_id stored in DB is tx_hash, that's not the internal orderId on contract.
            # The contract returns `bytes32 orderId`. It's emitted in event.
            # We need to capture that event to know the ID.
            # For now, if we assume order_id passed IS the bytes32 hex:
            
            if order_id.startswith("0x"):
                order_id_bytes = bytes.fromhex(order_id[2:])
            else:
                order_id_bytes = bytes.fromhex(order_id)
                
            session_account = self.w3_connector.w3.eth.account.from_key(session_key)
            nonce = await asyncio.to_thread(self.w3_connector.w3.eth.get_transaction_count, session_account.address)
            
            def build_cancel_tx():
                return order_router.functions.cancelOrder(
                    Web3.to_checksum_address(user_address),
                    order_id_bytes
                ).build_transaction({
                    'from': session_account.address,
                    'nonce': nonce,
                    'gas': 1000000 # Buffer
                })
                
            tx_data = await asyncio.to_thread(build_cancel_tx)
            
            signed_tx = await asyncio.to_thread(self.w3_connector.w3.eth.account.sign_transaction, tx_data, session_key)
            raw_tx = getattr(signed_tx, "raw_transaction", getattr(signed_tx, "rawTransaction", None))
            tx_hash = await asyncio.to_thread(self.w3_connector.w3.eth.send_raw_transaction, raw_tx)
            
            return {"status": "cancelling", "tx_hash": tx_hash.hex()}
            
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise e

    async def get_user_positions(self, user_address: str) -> List[Dict[str, Any]]:
        """
        Fetch positions from PositionManager contract.
        """
        try:
            if not self.w3_connector.w3.is_connected():
                return []
                
            # 1. Get Contract
            pm_contract = self.w3_connector.get_contract("PositionManager")
            
            # 2. Call View Function
            # getUserPositions returns Position[]
            # struct Position {
            #     bytes32 id;
            #     address user;
            #     string symbol;
            #     Side side; // uint8
            #     uint256 size; // USD 1e6?
            #     uint256 entryPrice; // 1e18?
            #     uint256 leverage;
            #     uint256 margin; // 1e6
            #     uint256 openTimestamp;
            #     bool isOpen;
            # }
            
            logger.info(f"Fetching on-chain positions for {user_address} using contract {pm_contract.address}...")
            raw_positions = pm_contract.functions.getUserPositions(Web3.to_checksum_address(user_address)).call()
            logger.info(f"Contract {pm_contract.address} returned {len(raw_positions)} raw positions.")
            
            positions = []
            for i, p in enumerate(raw_positions):
                logger.info(f"Raw Position [{i}]: {p}")
                # Tuple structure: 0:id, 1:user, 2:symbol, 3:side, 4:size(USD), 5:entryPrice, 6:leverage, 7:margin(USD), 8:timestamp, 9:isOpen
                
                if not p[9]: # Skip closed positions
                    continue

                pos_id = p[0].hex() if isinstance(p[0], bytes) else str(p[0])
                symbol = p[2]
                side_enum = p[3]
                side = "long" if side_enum == 0 else "short"
                
                size_usd = p[4] / 1_000_000.0 # Assuming 1e6 for USD values
                entry_price = p[5] / 1e6 # Contract stores price with 1e6 precision (per PositionManager.sol)
                leverage = p[6]
                margin_usd = p[7] / 1_000_000.0
                
                # Fetch current price from Hyperliquid/Ostium
                current_price = await self._get_current_price(symbol)
                
                # --- ROBUST FALLBACKS for Indexing Lag ---
                # 1. Fallback for size_usd if 0 (common lag)
                if size_usd == 0 and margin_usd > 0 and leverage > 0:
                    size_usd = margin_usd * leverage
                
                # 2. Fallback for entry_price if 0 (removed dynamic fallback to avoid flickering entry price)
                # If 0, the order_service will try to recover it from DB shadow positions
                
                # 3. Recalculate size_tokens with best available entry price
                eff_entry_price = entry_price if entry_price > 0 else current_price
                size_tokens = (size_usd / eff_entry_price) if eff_entry_price > 0 else 0
                
                # Calculate unrealized PnL
                unrealized_pnl = self._calculate_pnl(side, size_usd, entry_price, current_price)
                unrealized_pnl_percent = (unrealized_pnl / margin_usd * 100) if margin_usd > 0 else 0
                
                # Realized PnL from contract (p[10])
                realized_pnl = p[10] / 1e6 if len(p) > 10 else 0

                # Calculate liquidation price (80% loss of margin)
                liq_price = 0
                if size_usd > 0 and entry_price > 0:
                    max_loss_ratio = (margin_usd * 0.8) / size_usd
                    if side == 'long': 
                        liq_price = entry_price * (1 - max_loss_ratio)
                    else:  # short
                        liq_price = entry_price * (1 + max_loss_ratio)
                
                positions.append({
                    "id": pos_id,
                    "symbol": symbol,
                    "side": side,
                    "size": size_tokens,
                    "size_tokens": size_tokens,
                    "position_value": size_usd,
                    "entry_price": entry_price,
                    "mark_price": current_price,
                    "leverage": leverage,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_percent": unrealized_pnl_percent,
                    "realized_pnl": realized_pnl,
                    "liquidation_price": liq_price,
                    "item_id": pos_id,
                    "margin_used": margin_usd,
                    "exchange": "onchain",
                    "timestamp": p[8]
                })
                
            return positions
            
        except Exception as e:
            logger.error(f"Failed to fetch on-chain positions for {user_address} at {pm_contract.address if 'pm_contract' in locals() else 'unknown'}: {e}", exc_info=True)
            return []

    async def get_user_orders(self, user_address: str, status: str = None) -> List[Dict[str, Any]]:
        """
        Fetch orders from OrderRouter events:
        - OrderExecuted (indexed by user) → filled/market orders
        - OstiumOrderPlaced (indexed by user) → pending limit/stop orders
        """
        try:
            if not self.w3_connector.w3.is_connected():
                return []

            user_checksum = Web3.to_checksum_address(user_address)
            order_router = self.w3_connector.get_contract("OrderRouter")

            try:
                latest_block = self.w3_connector.w3.eth.block_number
                start_block = max(0, latest_block - 10000)
            except Exception:
                start_block = 0

            type_map = {0: "market", 1: "limit", 2: "stop_limit"}
            side_map = {0: "buy", 1: "sell"}
            status_map = {0: "unknown", 1: "open", 2: "open", 3: "filled", 4: "cancelled"}

            all_orders = []
            seen_ids = set()

            # --- Filled orders: OrderExecuted(orderId, user, executionPrice, pnl) ---
            try:
                filled_events = order_router.events.OrderExecuted.get_logs(
                    fromBlock=start_block,
                    toBlock='latest',
                    argument_filters={'user': user_checksum}
                )
            except Exception as e:
                logger.warning(f"OrderExecuted filter failed: {e}")
                filled_events = []

            for event in filled_events:
                args = event['args']
                order_id = args['orderId']
                order_id_hex = order_id.hex() if isinstance(order_id, bytes) else order_id
                if order_id_hex in seen_ids:
                    continue
                seen_ids.add(order_id_hex)

                if status and status.lower() == 'pending':
                    continue  # filled orders excluded from pending filter

                tx_hash = event['transactionHash'].hex()
                execution_price = args['executionPrice'] / 1e6

                # Decode original order params from calldata
                symbol, side_str, order_type_str, amount_usd, size, leverage = '', 'buy', 'market', 0.0, 0.0, 1
                try:
                    tx = await asyncio.to_thread(self.w3_connector.w3.eth.get_transaction, event['transactionHash'])
                    _, decoded = order_router.decode_function_input(tx['input'])
                    p = decoded['params']
                    symbol = p['symbol']
                    side_str = side_map.get(p['side'], 'buy')
                    order_type_str = type_map.get(p['orderType'], 'market')
                    amount_usd = p['amountUsd'] / 1_000_000.0
                    leverage = p['leverage']
                    size = (amount_usd / execution_price) if execution_price > 0 else 0.0
                except Exception as e:
                    logger.debug(f"Calldata decode failed for order {order_id_hex}: {e}")

                all_orders.append({
                    "id": order_id_hex,
                    "exchange_order_id": tx_hash,
                    "user_address": user_address,
                    "symbol": symbol,
                    "side": side_str,
                    "type": order_type_str,
                    "status": "filled",
                    "price": execution_price,
                    "size": size,
                    "amount_usd": amount_usd,
                    "leverage": leverage,
                    "timestamp": 0,
                    "exchange": "onchain"
                })

            # --- Pending/cancelled orders: OstiumOrderPlaced(orderId, ostiumOrderId, user, symbol) ---
            try:
                pending_events = order_router.events.OstiumOrderPlaced.get_logs(
                    fromBlock=start_block,
                    toBlock='latest',
                    argument_filters={'user': user_checksum}
                )
            except Exception as e:
                logger.warning(f"OstiumOrderPlaced filter failed: {e}")
                pending_events = []

            for event in pending_events:
                args = event['args']
                order_id = args['orderId']
                order_id_hex = order_id.hex() if isinstance(order_id, bytes) else order_id
                if order_id_hex in seen_ids:
                    continue  # already captured as filled

                try:
                    on_chain_status_code = order_router.functions.orders(order_id).call()
                    current_status = status_map.get(on_chain_status_code, "unknown")
                except Exception:
                    current_status = "unknown"

                if status:
                    if status.lower() == 'pending' and current_status not in ('open', 'pending', 'unknown'):
                        continue
                    elif status.lower() == 'history' and current_status not in ('filled', 'cancelled'):
                        continue

                seen_ids.add(order_id_hex)
                tx_hash = event['transactionHash'].hex()
                symbol = args['symbol']

                # Fetch stored params from contract (available while PENDING)
                amount_usd, side_str, order_type_str, leverage, price, size = 0.0, 'buy', 'limit', 1, 0.0, 0.0
                try:
                    p = order_router.functions.orderParams(order_id).call()
                    # tuple: (user, symbol, side, orderType, amountUsd, leverage, reduceOnly, postOnly, triggerCondition, price, stopPrice, timeInForce)
                    side_str = side_map.get(p[2], 'buy')
                    order_type_str = type_map.get(p[3], 'limit')
                    amount_usd = p[4] / 1_000_000.0
                    leverage = p[5]
                    price = p[9] / 1e6 if p[9] else 0.0
                    size = (amount_usd / price) if price > 0 else 0.0
                except Exception as e:
                    logger.debug(f"orderParams fetch failed for {order_id_hex}: {e}")

                all_orders.append({
                    "id": order_id_hex,
                    "exchange_order_id": tx_hash,
                    "user_address": user_address,
                    "symbol": symbol,
                    "side": side_str,
                    "type": order_type_str,
                    "status": current_status,
                    "price": price,
                    "size": size,
                    "amount_usd": amount_usd,
                    "leverage": leverage,
                    "timestamp": 0,
                    "exchange": "onchain"
                })

            if status and status.lower() == 'history':
                all_orders = [o for o in all_orders if o['status'] in ('filled', 'cancelled')]

            return all_orders

        except Exception as e:
            logger.error(f"Failed to fetch on-chain orders: {e}", exc_info=True)
            return []

    async def get_user_balances(self, user_address: str) -> Dict[str, float]:
        """Fetch user balances from TradingVault contract"""
        try:
            vault = self.w3_connector.get_contract("TradingVault")
            res = vault.functions.getBalance(Web3.to_checksum_address(user_address)).call()
            # Returns [total, reservedAmount, available]
            return {
                "account_value": res[0] / 1e6,
                "total_margin_used": res[1] / 1e6,
                "free_collateral": res[2] / 1e6
            }
        except Exception as e:
            logger.error(f"Failed to fetch on-chain balances for {user_address}: {e}")
            return {
                "account_value": 0,
                "total_margin_used": 0,
                "free_collateral": 0
            }
    async def get_vault_transfers(self, user_address: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch deposit/withdraw history directly from TradingVault events.
        """
        try:
            vault_contract = self.w3_connector.get_contract("TradingVault")
            if not vault_contract:
                return []

            user_checksum = Web3.to_checksum_address(user_address)
            
            # Fetch current block for range control
            try:
                current_block = self.w3_connector.w3.eth.block_number
            except Exception:
                current_block = 0 

            # Fallback range to 1.0M blocks (~3 days) to be safer and faster
            from_block = max(0, current_block - 1000000)
            logger.info(f"Fetching funding history for {user_address} from block {from_block} to latest")

            def fetch_logs(contract_event, user_checksum, start_block):
                try:
                    return contract_event.get_logs(
                        fromBlock=start_block,
                        toBlock='latest',
                        argument_filters={'user': user_checksum}
                    )
                except Exception as e:
                    logger.warning(f"Primary RPC get_logs failed for {contract_event.event_name}, trying backup: {e}")
                    try:
                        if not self._backup_w3:
                            backup_url = getattr(settings, "ARBITRUM_BACKUP_RPC_URL", "https://base-sepolia-rpc.publicnode.com")
                            self._backup_w3 = Web3(Web3.HTTPProvider(backup_url, request_kwargs={'timeout': 15}))

                        vault_addr = Web3.to_checksum_address(settings.TRADING_VAULT_ADDRESS)
                        vault_backup = self._backup_w3.eth.contract(address=vault_addr, abi=vault_contract.abi)
                        event_backup = getattr(vault_backup.events, contract_event.event_name)

                        return event_backup.get_logs(
                            fromBlock=start_block,
                            toBlock='latest',
                            argument_filters={'user': user_checksum}
                        )
                    except Exception as backup_e:
                        logger.error(f"Backup RPC also failed for {contract_event.event_name}: {backup_e}")
                        return []

            deposits = fetch_logs(vault_contract.events.CollateralDeposited, user_checksum, from_block)
            withdrawals = fetch_logs(vault_contract.events.CollateralWithdrawn, user_checksum, from_block)
            
            all_events = []
            for d in deposits:
                all_events.append(('Deposit', d))
            for w in withdrawals:
                all_events.append(('Withdraw', w))
            
            # Sort all events by block number descending
            # In Web3.py v7, event objects have 'blockNumber' attribute or can be accessed as dict
            def get_block_num(ev):
                return ev.get('blockNumber', 0) if isinstance(ev, dict) else getattr(ev, 'blockNumber', 0)

            all_events.sort(key=lambda x: get_block_num(x[1]), reverse=True)
            active_events = all_events[:limit]
            
            history = []
            for event_type, d in active_events:
                try:
                    block_num = get_block_num(d)
                    
                    # Timestamp fetching with cache
                    ts = None
                    if block_num in self._block_cache:
                        ts = self._block_cache[block_num]
                    else:
                        try:
                            # Synchronous call
                            block = self.w3_connector.w3.eth.get_block(block_num)
                            ts = block['timestamp']
                            self._block_cache[block_num] = ts
                        except:
                            if self._backup_w3:
                                try:
                                    block = self._backup_w3.eth.get_block(block_num)
                                    ts = block['timestamp']
                                    self._block_cache[block_num] = ts
                                except: pass
                    
                    if ts is None:
                        ts = int(datetime.utcnow().timestamp())
                    
                    tx_hash = d.get('transactionHash', b'').hex() if isinstance(d, dict) else d.transactionHash.hex()
                    
                    history.append({
                        "id": tx_hash,
                        "type": event_type,
                        "asset": "USDC",
                        "amount": float(d['args']['amount']) / 1e6,
                        "txHash": tx_hash,
                        "status": "Completed",
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                    })
                except Exception as e:
                    logger.warning(f"Error processing funding event: {e}")
                    continue

            return history
            
        except Exception as e:
            logger.error(f"Failed to fetch vault transfers: {e}", exc_info=True)
            return []
