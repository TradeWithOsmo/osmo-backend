import json
import logging
from pathlib import Path
from typing import Any, Optional, Dict, List
from web3 import Web3
from web3.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

try:
    from backend.websocket.config import settings
except ImportError:
    try:
        from websocket.config import settings
    except ImportError:
        from config import settings

logger = logging.getLogger(__name__)

class ArbitrumWeb3Connector:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ArbitrumWeb3Connector, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
            
        self.network_mode = settings.NETWORK_MODE
        self.chain_id = settings.CHAIN_ID
        self.contracts: Dict[str, Contract] = {}
        
        # Initialize Web3
        self.w3 = Web3(Web3.HTTPProvider(
            settings.ARBITRUM_RPC_URL,
            request_kwargs={'timeout': settings.WEB3_PROVIDER_TIMEOUT}
        ))
        
        # Add middleware for POA chains if needed (Arbitrum handles this, but good practice)
        # Web3.py v7 uses middleware_onion or distinct middleware management.
        # Ensure we use the class directly.
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        # Verify connection
        if not self.w3.is_connected():
            logger.warning(f"Primary RPC {settings.ARBITRUM_RPC_URL} failed, trying backup...")
            self.w3 = Web3(Web3.HTTPProvider(settings.ARBITRUM_BACKUP_RPC_URL))
            
            if not self.w3.is_connected():
                logger.error("Failed to connect to both primary and backup RPCs")
                # Don't raise here to allow service to start, but mark as unhealthy?
        else:
            logger.info(f"✅ Connected to {self.network_mode}")

        # Check Chain ID
        try:
            actual_chain_id = self.w3.eth.chain_id
            if actual_chain_id != self.chain_id:
                logger.error(f"Chain ID mismatch! Configured: {self.chain_id}, Actual: {actual_chain_id}")
            else:
                logger.info(f"Chain ID verified: {self.chain_id}")
        except Exception as e:
            logger.error(f"Failed to verify chain ID: {e}")

        # Load Account if key exists
        self.account = None
        if settings.TREASURY_PRIVATE_KEY:
            try:
                self.account = Account.from_key(settings.TREASURY_PRIVATE_KEY)
                logger.info(f"Loaded Treasury Account: {self.account.address}")
            except Exception as e:
                logger.error(f"Failed to load Treasury Account: {e}")

        self.initialized = True

    def get_contract(self, contract_name: str) -> Contract:
        """Get or load a contract instance"""
        if contract_name in self.contracts:
            return self.contracts[contract_name]
            
        # Get address from settings
        # Convert CamelCase/PascalCase to SNAKE_CASE while preserving acronyms.
        # Examples:
        # - TradingVault -> TRADING_VAULT
        # - SessionKeyManager -> SESSION_KEY_MANAGER
        # - AIVault -> AI_VAULT
        # - USDC -> USDC
        import re
        snake_name = re.sub(
            r'(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])',
            '_',
            contract_name,
        ).upper()
        
        env_var_name = f"{snake_name}_ADDRESS"
        address = getattr(settings, env_var_name, None)
        
        if not address:
            raise ValueError(f"Contract address not configured for {contract_name} (Expected {env_var_name})")
            
        # Load ABI
        try:
            # Assuming running from backend root
            abi_path = Path("backend/contracts/abis") / f"{contract_name}.json"
            if not abi_path.exists():
                # Try relative to file
                abi_path = Path(__file__).parent.parent.parent / "contracts" / "abis" / f"{contract_name}.json"
                
            with open(abi_path) as f:
                abi_data = json.load(f)
                # Handle Foundry artifact structure or raw ABI list
                if isinstance(abi_data, dict):
                    abi = abi_data.get('abi', abi_data)
                else:
                    abi = abi_data
                
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(address),
                abi=abi
            )
            
            self.contracts[contract_name] = contract
            return contract
        except Exception as e:
            logger.error(f"Failed to load contract {contract_name}: {e}")
            raise

    async def get_balance(self, address: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(address))

    async def get_block_number(self) -> int:
        return self.w3.eth.block_number

# Singleton instance
web3_connector = ArbitrumWeb3Connector()
