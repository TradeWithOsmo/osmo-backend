import asyncio
import logging
import json
import httpx
from typing import Set, Dict, Callable, Optional
from config import settings

logger = logging.getLogger(__name__)

class BridgeMonitor:
    """Monitors Arbitrum Bridge Contract for Deposit events"""
    
    # Event Signature: Deposit(address,uint256)
    # Keccak-256: 0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c
    DEPOSIT_TOPIC = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
    
    def __init__(self):
        self.rpc_url = settings.ARBITRUM_RPC_URL
        self.contract_address = settings.BRIDGE_CONTRACT_ADDRESS
        self.poll_interval = settings.BRIDGE_POLL_INTERVAL
        self.subnet_subscriptions: Dict[str, Set[Callable]] = {} # address -> set of callbacks
        self.is_running = False
        self.last_block = "latest"
        
    async def start(self):
        """Start the polling loop"""
        if not self.contract_address:
            logger.warning("Bridge Monitor disabled: No BRIDGE_CONTRACT_ADDRESS configured")
            return

        self.is_running = True
        logger.info(f"🌉 Bridge Monitor started for {self.contract_address}")
        asyncio.create_task(self._poll_loop())

    async def stop(self):
        """Stop the polling loop"""
        self.is_running = False
        logger.info("Bridge Monitor stopped")

    async def subscribe(self, address: str, callback: Callable):
        """Subscribe to deposits for a specific address"""
        address = address.lower()
        if address not in self.subnet_subscriptions:
            self.subnet_subscriptions[address] = set()
        self.subnet_subscriptions[address].add(callback)
        logger.debug(f"Subscribed to bridge deposits for {address}")

    async def unsubscribe(self, address: str, callback: Callable):
        """Unsubscribe"""
        address = address.lower()
        if address in self.subnet_subscriptions:
            self.subnet_subscriptions[address].discard(callback)
            if not self.subnet_subscriptions[address]:
                del self.subnet_subscriptions[address]

    async def _poll_loop(self):
        """Main polling loop"""
        while self.is_running:
            try:
                await self._check_logs()
            except Exception as e:
                logger.error(f"Bridge poll failed: {e}")
            
            await asyncio.sleep(self.poll_interval)

    async def _check_logs(self):
        """Fetch logs from RPC"""
        # Get latest block number first
        async with httpx.AsyncClient() as client:
            # 1. Get Block Number
            payload_block = {
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1
            }
            resp = await client.post(self.rpc_url, json=payload_block)
            current_block_hex = resp.json().get("result")
            current_block = int(current_block_hex, 16)
            
            if self.last_block == "latest":
                self.last_block = current_block - 10 # Start 10 blocks back
            
            if current_block <= self.last_block:
                return # No new blocks

            # 2. Get Logs
            from_block = hex(self.last_block + 1)
            to_block = hex(current_block)
            
            payload_logs = {
                "jsonrpc": "2.0",
                "method": "eth_getLogs",
                "params": [{
                    "address": self.contract_address,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": [self.DEPOSIT_TOPIC]
                }],
                "id": 2
            }
            
            resp_logs = await client.post(self.rpc_url, json=payload_logs)
            logs = resp_logs.json().get("result", [])
            
            for log in logs:
                await self._process_log(log)
            
            self.last_block = current_block

    async def _process_log(self, log: dict):
        """Process a single log entry"""
        topics = log.get("topics", [])
        if not topics or len(topics) < 2:
            return
            
        # Topic 1 is the user address (padded to 32 bytes)
        # 0x0000000000000000000000001234567890abcdef1234567890abcdef12345678
        user_address_padded = topics[1]
        user_address = "0x" + user_address_padded[-40:] # Last 20 bytes (40 hex chars)
        
        logger.info(f"Bridge Deposit detected for {user_address}")
        
        if user_address in self.subnet_subscriptions:
            # Extract amount (data)
            data = log.get("data", "0x0")
            amount = int(data, 16) / 1e6 # Assuming USDC (6 decimals)
            
            message = {
                "type": "bridge_deposit",
                "user": user_address,
                "amount": amount,
                "tx_hash": log.get("transactionHash")
            }
            
            # Notify subscribers
            for callback in self.subnet_subscriptions[user_address]:
                await callback(message)

# Global Instance
bridge_monitor = BridgeMonitor()
