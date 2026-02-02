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
            # call canClaim(address) -> (bool, uint256)
            can_claim, cooldown = contract.functions.canClaim(user_address).call()
            return can_claim, cooldown
        except Exception as e:
            logger.error(f"Faucet eligibility check failed: {e}")
            # Fault-tolerant fallback: allow claim if contract error (e.g. not deployed yet in dev)
            return True, 0

    async def get_faucet_balance(self) -> float:
        """Get current USDC balance inside the faucet"""
        try:
            faucet_contract = self.connector.get_contract("Faucet")
            usdc_contract = self.connector.get_contract("USDC")
            
            balance = usdc_contract.functions.balanceOf(faucet_contract.address).call()
            return balance / 1_000_000 # USDC 6 decimals
        except Exception as e:
            logger.error(f"Failed to fetch faucet balance: {e}")
            return 0.0

    async def claim(self, user_address: str) -> dict:
        """
        Execute a faucet claim for the user.
        In testnet, this is usually mediated by the backend treasury.
        """
        try:
            contract = self.connector.get_contract("Faucet")
            if not self.connector.account:
                 return {"success": False, "message": "Treasury account not available in backend"}
            
            # Build and send transaction
            # Note: This is a blocking call in standard web3.py for simplicity here, 
            # ideally should be offloaded if high frequency.
            
            # 1. Build transaction
            nonce = self.connector.w3.eth.get_transaction_count(self.connector.account.address)
            
            # Simple drip call - Adjust function name 'claim' or 'drip' to match ABI
            tx = contract.functions.claim(user_address).build_transaction({
                'from': self.connector.account.address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': self.connector.w3.eth.gas_price
            })
            
            # 2. Sign and send
            signed_tx = self.connector.w3.eth.account.sign_transaction(tx, self.connector.account.key)
            tx_hash = self.connector.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            logger.info(f"Faucet claim successful for {user_address}: {tx_hash.hex()}")
            
            return {
                "success": True, 
                "message": "Tokens sent successfully!",
                "tx_hash": tx_hash.hex()
            }
            
        except Exception as e:
            logger.error(f"Faucet claim failed: {e}")
            return {"success": False, "message": str(e)}

# Export singleton
faucet_manager = FaucetManager()
