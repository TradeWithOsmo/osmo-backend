import logging
import time
from typing import Tuple, Optional
from .connector import web3_connector

logger = logging.getLogger(__name__)

class FaucetManager:
    """Manages blockchain faucet interactions for test tokens"""
    
    def __init__(self):
        self.connector = web3_connector
        
    async def check_eligibility(self, user_address: str) -> Tuple[bool, int]:
        """
        Check if user is eligible to claim from faucet.
        Returns (can_claim, time_until_next_claim_seconds)
        """
        try:
            contract = self.connector.get_contract("Faucet")
            can_claim = contract.functions.canDrip(user_address).call()
            cooldown = contract.functions.timeUntilNextDrip(user_address).call()
            return bool(can_claim), int(cooldown)
        except Exception as e:
            logger.error(f"Faucet eligibility check failed: {e}")
            # Fault-tolerant fallback: allow claim if contract error (e.g. not deployed yet in dev)
            return True, 0

    async def get_faucet_balance(self) -> float:
        """Get current USDC balance inside the faucet"""
        try:
            faucet_contract = self.connector.get_contract("Faucet")
            balance = faucet_contract.functions.getFaucetBalance().call()
            return balance / 1_000_000  # USDC 6 decimals
        except Exception as e:
            logger.error(f"Failed to fetch faucet balance: {e}")
            return 0.0

    async def claim(self, user_address: str) -> dict:
        """
        Execute a faucet claim for the user.
        In testnet, this is usually mediated by the backend treasury.
        """
        # Faucet.drip() always sends to msg.sender, so backend cannot claim on behalf of an arbitrary user.
        return {
            "success": False,
            "message": "Backend faucet claim is not supported. Please claim on-chain by calling Faucet.drip() from your wallet."
        }

# Export singleton
faucet_manager = FaucetManager()
