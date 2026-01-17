"""
Chainlink Connector

Price feed oracle for verification and fallback.
"""

from ..base_connector import BaseConnector, ConnectorStatus
from typing import Dict, Any, Callable
from web3 import Web3
from web3.contract import Contract
import os


# Chainlink Price Feed ABI (minimal - just latestRoundData)
PRICE_FEED_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Chainlink Price Feed addresses on Arbitrum
PRICE_FEEDS = {
    "BTC-USD": "0x6ce185860a4963106506C203335A2910413708e9",  # Arbitrum
    "ETH-USD": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",  # Arbitrum
    "SOL-USD": "0x24ceA4b8ce57cdA5058b924B9B9987992450590c",  # Arbitrum
    # Add more as needed
}


class ChainlinkConnector(BaseConnector):
    """
    Chainlink oracle price feed connector.
    
    Purpose:
    - Fallback price verification when DEX feeds unavailable
    - Oracle price for GP/GL calculation
    - Cross-verification with DEX prices
    
    Network: Arbitrum (free RPC)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("chainlink", config)
        
        self.rpc_url = config.get(
            "rpc_url",
            os.getenv("CHAINLINK_RPC_URL", "https://arb1.arbitrum.io/rpc")
        )
        self.backup_rpc = config.get(
            "backup_rpc",
            os.getenv("CHAINLINK_BACKUP_RPC", "https://arbitrum.llamarpc.com")
        )
        
        # Initialize Web3
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.w3.is_connected():
                # Try backup RPC
                self.w3 = Web3(Web3.HTTPProvider(self.backup_rpc))
            
            if self.w3.is_connected():
                self.status = ConnectorStatus.HEALTHY
            else:
                self.status = ConnectorStatus.OFFLINE
        except Exception as e:
            print(f"Chainlink RPC connection failed: {e}")
            self.status = ConnectorStatus.ERROR
        
        self._contracts = {}  # Cache contract instances
    
    async def fetch(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """
        Fetch oracle price for symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTC-USD", "ETH-USD")
            **kwargs: Additional parameters
        
        Returns:
            Normalized price data
        """
        try:
            # Get or create contract
            contract = self._get_contract(symbol)
            if not contract:
                raise ValueError(f"No Chainlink feed for {symbol}")
            
            # Call latestRoundData
            round_data = contract.functions.latestRoundData().call()
            decimals = contract.functions.decimals().call()
            
            # Parse response
            raw_price = round_data[1]  # answer
            updated_at = round_data[3]  # updatedAt
            
            # Convert to decimal price
            price = raw_price / (10 ** decimals)
            
            raw_data = {
                "symbol": symbol,
                "price": price,
                "updatedAt": updated_at,
                "decimals": decimals,
                "roundId": round_data[0]
            }
            
            return self.normalize(raw_data)
        
        except Exception as e:
            self.status = ConnectorStatus.ERROR
            raise Exception(f"Chainlink fetch error for {symbol}: {e}")
    
    async def subscribe(
        self,
        symbol: str,
        callback: Callable,
        **kwargs
    ) -> None:
        """
        Chainlink doesn't support subscriptions (read-only oracle).
        
        For real-time updates, poll at intervals.
        """
        raise NotImplementedError(
            "Chainlink is read-only oracle. Use polling for updates."
        )
    
    def _get_contract(self, symbol: str) -> Contract:
        """Get or create Web3 contract instance"""
        if symbol in self._contracts:
            return self._contracts[symbol]
        
        # Get feed address
        feed_address = PRICE_FEEDS.get(symbol)
        if not feed_address:
            return None
        
        # Create contract
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(feed_address),
            abi=PRICE_FEED_ABI
        )
        
        self._contracts[symbol] = contract
        return contract
    
    def normalize(self, raw_data: Any) -> Dict[str, Any]:
        """
        Normalize Chainlink data to standard format.
        
        Args:
            raw_data: Raw oracle data
        
        Returns:
            {
                "source": "chainlink",
                "symbol": symbol,
                "data_type": "price",
                "timestamp": int,
                "data": {
                    "price": float,
                    "oracle_type": "chainlink"
                }
            }
        """
        return {
            "source": "chainlink",
            "symbol": raw_data.get("symbol", "UNKNOWN"),
            "data_type": "price",
            "timestamp": raw_data.get("updatedAt", 0),
            "data": {
                "price": float(raw_data.get("price", 0)),
                "oracle_type": "chainlink",
                "decimals": raw_data.get("decimals", 8)
            }
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get connector health status"""
        status = super().get_status()
        status["rpc_connected"] = self.w3.is_connected() if hasattr(self, 'w3') else False
        status["supported_feeds"] = list(PRICE_FEEDS.keys())
        return status
