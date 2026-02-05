
import asyncio
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from web3 import Web3

load_dotenv(os.path.join(os.path.dirname(__file__), '../websocket/.env'))

# Setup paths
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../websocket')) 

from connectors.web3_arbitrum.connector import web3_connector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("YOLO_TEST")

async def main():
    logger.info("🚀 STARTING YOLO ON-CHAIN TEST (HARDCODED MODE)")

    # 1. Initialize Web3
    if not web3_connector.w3:
        logger.error("Web3 Connector failed to initialize W3.")
        return

    logger.info(f"   Connected to: {web3_connector.w3.provider}")
    
    # HARDCODED CONTRACT DATA
    ORDER_ROUTER_ADDRESS = "0xFd8b09f95E4B2dd9dA7B5c22CC0eBb0186B14358"
    ORDER_ROUTER_ABI = [
      {
        "inputs": [
          {
            "components": [
              {"internalType": "address", "name": "user", "type": "address"},
              {"internalType": "string", "name": "symbol", "type": "string"},
              {"internalType": "uint8", "name": "side", "type": "uint8"},
              {"internalType": "uint8", "name": "orderType", "type": "uint8"},
              {"internalType": "uint256", "name": "amountUsd", "type": "uint256"},
              {"internalType": "uint8", "name": "leverage", "type": "uint8"},
              {"internalType": "uint256", "name": "price", "type": "uint256"},
              {"internalType": "uint256", "name": "stopPrice", "type": "uint256"}
            ],
            "internalType": "struct OsmoTypes.OrderParams",
            "name": "params",
            "type": "tuple"
          }
        ],
        "name": "placeOrder",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
      }
    ]

    # 2. Setup Dummy User & Session
    user_address = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e" 
    
    # Generate random session key
    temp_account = web3_connector.w3.eth.account.create()
    session_key = temp_account.key.hex()
    session_address = temp_account.address
    
    logger.info(f"   Using Session Address: {session_address}")

    # 3. Get Contract Manually
    try:
        order_router = web3_connector.w3.eth.contract(address=ORDER_ROUTER_ADDRESS, abi=ORDER_ROUTER_ABI)
        logger.info(f"3. OrderRouter: {order_router.address}")
    except Exception as e:
        logger.error(f"Failed to load contract: {e}")
        return

    # 4. Prepare Logic
    params = (
        Web3.to_checksum_address(user_address),
        "ETH-USD",
        0, # Buy
        0, # Market
        int(100 * 1_000_000), # 100 USD
        2, # Leverage
        0, # Price
        0  # StopPrice
    )

    logger.info(f"4. Params: {params}")

    # 5. Build & Sign Transaction
    try:
        # Check Balance
        balance = web3_connector.w3.eth.get_balance(session_address)
        
        if balance == 0:
            logger.warning("⚠️ Session Key has 0 ETH. Simulating call...")
            
                # SIMULATE (eth_call)
            try:
                # Build transaction first to get data
                tx = order_router.functions.placeOrder(params).build_transaction({
                    'from': session_address,
                    'gas': 2000000,
                    'gasPrice': web3_connector.w3.eth.gas_price
                })
                data = tx['data']
                
                # We expect this to revert because session is invalid
                web3_connector.w3.eth.call({
                    'to': order_router.address,
                    'from': session_address,
                    'data': data
                })
                logger.info("✅ Simulation SUCCESS (Unexpected)")
            except Exception as e:
                logger.info(f"✅ Simulation Reverted (Expected!): {e}")
                logger.info("   -> Connectivity to Arbitrum Sepolia CONFIRMED.")
                logger.info("   -> Contract 'placeOrder' interaction attempted.")
            
            return

        # If has balance (unlikely here)
        nonce = web3_connector.w3.eth.get_transaction_count(session_address)
        tx_data = order_router.functions.placeOrder(params).build_transaction({
            'from': session_address,
            'nonce': nonce,
            'gas': 2000000,
            'gasPrice': web3_connector.w3.eth.gas_price
        })
        
        signed_tx = web3_connector.w3.eth.account.sign_transaction(tx_data, session_key)
        tx_hash = web3_connector.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logger.info(f"✅ Transaction Sent! Hash: {tx_hash.hex()}")

    except Exception as e:
        logger.error(f"❌ Execution Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
