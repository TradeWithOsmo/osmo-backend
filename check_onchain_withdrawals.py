
import asyncio
import sys
import os
from web3 import Web3

sys.path.append(os.path.abspath("backend/websocket"))
from config import settings

TRADING_VAULT_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newBalance", "type": "uint256"}
        ],
        "name": "CollateralDeposited",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "remainingBalance", "type": "uint256"}
        ],
        "name": "CollateralWithdrawn",
        "type": "event"
    }
]

async def check_events():
    w3 = Web3(Web3.HTTPProvider(settings.ARBITRUM_RPC_URL))
    vault_addr = Web3.to_checksum_address(settings.TRADING_VAULT_ADDRESS)
    vault = w3.eth.contract(address=vault_addr, abi=TRADING_VAULT_ABI)
    
    end_block = w3.eth.block_number
    start_block = end_block - 10000 # check last 10k blocks
    
    print(f"Checking events from {start_block} to {end_block}...")
    
    try:
        deposits = vault.events.CollateralDeposited.get_logs(from_block=start_block, to_block=end_block)
        print(f"Found {len(deposits)} Deposits")
        
        withdrawals = vault.events.CollateralWithdrawn.get_logs(from_block=start_block, to_block=end_block)
        print(f"Found {len(withdrawals)} Withdrawals")
        for w in withdrawals:
            print(f"Withdrawal: {w['args']['user']} - {w['args']['amount']/1e6} USDC - Tx: {w['transactionHash'].hex()}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_events())
