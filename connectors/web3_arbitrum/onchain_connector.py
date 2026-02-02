import logging
import asyncio
from typing import Dict, Any, List, Optional
from web3 import Web3

from connectors.base_connector import BaseConnector, ConnectorStatus
from connectors.web3_arbitrum.connector import web3_connector
from connectors.web3_arbitrum.session_manager import session_manager
try:
    from websocket.config import settings
except ImportError:
    from config import settings

logger = logging.getLogger(__name__)

class OnchainConnector(BaseConnector):
    """
    Connector for On-Chain Trading via OrderRouter smart contract.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("onchain", config)
        self.w3_connector = web3_connector
        self.status = ConnectorStatus.HEALTHY if self.w3_connector.initialized else ConnectorStatus.OFFLINE

    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch on-chain price or data.
        For now, this might just return Oracle price if needed, or be no-op.
        """
        # Could fetch price from Chainlink oracle via w3_connector
        return {}

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
        size: float, # On-chain this might be AmountUSD? Or unit?
        # Note: OrderRouter.placeOrder takes amountUsd.
        # OrderService passes 'amount_usd'. But signature says 'size'.
        # We need to map correctly. 
        # BaseConnector signature: place_order(..., size, ...)
        # In OrderService logic:
        # if exchange == 'hyperliquid': size = amount_usd / price
        # else: size = amount_usd (for Ostium)
        # For Onchain, we probably want amount_usd.
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place order via OrderRouter contract using Session Key.
        """
        try:
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
            
            # OrderType: 0=MARKET, 1=LIMIT, 2=STOP_LIMIT (Assuming standard mapping, verify ABI)
            order_type_map = {
                'market': 0,
                'limit': 1,
                'stop_limit': 2,
                'stop': 2 # Handle 'stop' as stop_limit or separate? Assuming stop_limit for now
            }
            order_type_enum = order_type_map.get(order_type.lower(), 0)
            
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
            # Safest is to assume standard logic: 
            # amountUsd -> 1e6 (since it matches USDC collateral)
            # price -> 1e18 (standard precision)
            
            usd_decimals = 1_000_000 # 6 decimals
            price_decimals = 1_000_000_000_000_000_000 # 18 decimals
            
            amount_usd_int = int(size * usd_decimals) # Interpreting 'size' as AmountUSD here
            price_int = int(price * price_decimals) if price else 0
            stop_price_int = int(stop_price * price_decimals) if stop_price else 0
            leverage = int(kwargs.get('leverage', 1))
            
            params = (
                Web3.to_checksum_address(user_address),
                symbol,
                side_enum,
                order_type_enum,
                amount_usd_int,
                leverage,
                price_int,
                stop_price_int
            )
            
            # 4. Build Transaction
            # We need the address of the SESSION KEY that is signing, NOT the user.
            # The transaction is sent FROM the session key.
            # The OrderRouter.placeOrder checks if msg.sender is a valid session key for params.user
            
            session_account = self.w3_connector.w3.eth.account.from_key(session_key)
            session_address = session_account.address
            
            # Estimate Gas
            # Note: We need a way to get nonce for the session key address
            nonce = self.w3_connector.w3.eth.get_transaction_count(session_address)
            
            # Construct standard tx
            tx_data = order_router.functions.placeOrder(params).build_transaction({
                'from': session_address,
                'nonce': nonce,
                'gas': 2000000, # Fallback, ideally estimate
                'gasPrice': self.w3_connector.w3.eth.gas_price
            })
            
            # 5. Sign Transaction
            signed_tx = self.w3_connector.w3.eth.account.sign_transaction(tx_data, session_key)
            
            # 6. Send Transaction
            tx_hash = self.w3_connector.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            logger.info(f"On-chain order placed: {tx_hash_hex}")
            
            return {
                "exchange": "onchain",
                "exchange_order_id": tx_hash_hex, # Use tx hash as ID for now
                "status": "pending",
                "raw_response": {"tx_hash": tx_hash_hex}
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
            nonce = self.w3_connector.w3.eth.get_transaction_count(session_account.address)
            
            tx_data = order_router.functions.cancelOrder(
                Web3.to_checksum_address(user_address),
                order_id_bytes
            ).build_transaction({
                'from': session_account.address,
                'nonce': nonce,
                'gas': 500000,
                'gasPrice': self.w3_connector.w3.eth.gas_price
            })
            
            signed_tx = self.w3_connector.w3.eth.account.sign_transaction(tx_data, session_key)
            tx_hash = self.w3_connector.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            return {"status": "cancelling", "tx_hash": tx_hash.hex()}
            
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise e

    async def get_user_positions(self, user_address: str) -> List[Dict[str, Any]]:
        """
        Get positions from TradingVault?
        """
        # TODO: Implement reading positions from contract
        return []

    async def get_user_orders(self, user_address: str, status: str = None) -> List[Dict[str, Any]]:
        # Usually read from Indexer/TheGraph
        return []
