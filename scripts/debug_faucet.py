
import asyncio
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from web3 import Web3

load_dotenv(os.path.join(os.path.dirname(__file__), '../websocket/.env'))

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../websocket')) 

from connectors.web3_arbitrum.connector import web3_connector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FAUCET_TEST")

async def main():
    logger.info("🚀 STARTING FAUCET DEBUG TEST")

    if not web3_connector.w3:
        logger.error("Web3 Connector failed.")
        return

    # FAUCET & USDC ADDRESS FROM addresses.json
    FAUCET_ADDRESS = "0x921daADeaC569aDEB234e2Ca4bfcA7104A6efD2f"
    USDC_ADDRESS = "0x891BAcc68c2cf6609AFD9FD2A0CA5E28AF037128"

    FAUCET_ABI = [
        {
            "inputs": [{"name": "token", "type": "address"}],
            "name": "dripToken",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]

    # Use a dummy account (or the user's if provided, but we don't have their key)
    # We'll use a random account. 
    # NOTE: Faucet usually drips to msg.sender.
    # If we use a random account with 0 ETH, we can only simulate (eth_call).
    # If the Faucet has a check "msg.sender must have ETH" (unlikely) or "limit per IP" (unlikely onchain),
    # The most common check is "limit per address".
    
    temp_account = web3_connector.w3.eth.account.create()
    session_address = temp_account.address
    logger.info(f"   Testing with Random Address: {session_address}")

    # ERC20 ABI to check balance
    ERC20_ABI = [
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
    ]
    
    usdc = web3_connector.w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    balance = usdc.functions.balanceOf(FAUCET_ADDRESS).call()
    logger.info(f"   Faucet USDC Balance: {balance / 1_000_000} USDC")

    if balance < 1000 * 1_000_000:
        logger.warning("⚠️ FAUCET IS EMPTY OR LOW BALANCE! This is likely why it reverts.")

    # Try MINT directly on USDC
    USDC_ABI = [
        {
            "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
            "name": "mint",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    usdc_contract = web3_connector.w3.eth.contract(address=USDC_ADDRESS, abi=USDC_ABI)

    try:
        # SIMULATE (eth_call)
        # mint(session_address, 1000 USDC)
        
        amount = 1000 * 1_000_000
        
        tx = usdc_contract.functions.mint(session_address, amount).build_transaction({
            'from': session_address,
            'gas': 2000000,
            'gasPrice': web3_connector.w3.eth.gas_price
        })
        # Simulating Mint
        logger.info("   Simulating USDC.mint(session_address, 1000)...")
        
        # Check Balance BEFORE
        balance_before = usdc_contract.functions.balanceOf(session_address).call()
        logger.info(f"   Balance BEFORE: {balance_before / 1_000_000} USDC")

        tx = usdc_contract.functions.mint(session_address, amount).build_transaction({
            'from': session_address,
            'gas': 2000000,
            'gasPrice': web3_connector.w3.eth.gas_price
        })
        data = tx['data']
        
        # Execute Call
        web3_connector.w3.eth.call({
            'to': USDC_ADDRESS,
            'from': session_address,
            'data': data
        })
        logger.info("✅ Simulation SUCCESS! USDC.mint is PUBLIC.")
        
        # Note: eth_call does NOT persist state, so we can't check balance AFTER in a standard node.
        # However, if it didn't revert, it means it's allowed.
        # To verify persistence, we'd need to send a REAL transaction (which needs ETH).
        # We can't do that with a random fresh account.
        
        logger.info("ℹ️  Note: Since we are using eth_call (simulation) with a 0-ETH account, state is not persisted.")
        logger.info("    However, the lack of REVERT confirms the function is accessible.")

    except Exception as e:
        logger.error(f"❌ Simulation FAILED / REVERTED: {e}")
        logger.info("   -> USDC.mint is likely RESTRICTED (Ownable).")
        
    except Exception as e:
        logger.error(f"❌ Simulation FAILED / REVERTED: {e}")
        # Try to decode if possible, but usually e contains the string

if __name__ == "__main__":
    asyncio.run(main())
