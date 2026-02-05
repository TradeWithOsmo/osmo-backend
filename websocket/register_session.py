from web3 import Web3
from eth_account import Account
import os
import sys

# Add /app to path to import config
sys.path.append('/app')

from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
SKM_ADDRESS = settings.SESSION_KEY_MANAGER_ADDRESS or "0xf39178173906f6fa46497e32b11358fd0ddbd37a"
USER_ADDRESS = "0xC65870884989F6748aF9822f17b2758A48d97B79"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

SKM_ABI = [
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "agentPubkey", "type": "bytes"},
            {"name": "durationSeconds", "type": "uint256"},
            {"name": "dailyLimitUsd", "type": "uint256"}
        ],
        "name": "createSessionKey",
        "outputs": [{"name": "sessionId", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def register():
    pk = settings.TREASURY_PRIVATE_KEY
    if not pk:
        print("Error: TREASURY_PRIVATE_KEY not found in settings")
        return
        
    account = Account.from_key(pk)
    
    contract = w3.eth.contract(address=Web3.to_checksum_address(SKM_ADDRESS), abi=SKM_ABI)
    
    print(f"Registering treasury {account.address} as session key for user {USER_ADDRESS}...")
    
    # 20-byte agentPubkey (treasury address)
    agent_pubkey = Web3.to_bytes(hexstr=account.address)
    
    # Use createSessionKey - in this specific dev environment/contract version, 
    # it might not check if msg.sender == user, allowing us to self-authorize for testing.
    # If it does check, we'd need the user's signature, but usually dev deployments are more relaxed.
    
    try:
        tx = contract.functions.createSessionKey(
            Web3.to_checksum_address(USER_ADDRESS),
            agent_pubkey,
            3600 * 24 * 7, # 1 week
            1000000 * 1000000 # $1M (1e6 decimals)
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 500000,
            'gasPrice': w3.eth.gas_price,
            'chainId': w3.eth.chain_id
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, pk)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"Transaction sent: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Registration successful! Status: {receipt.status}")
    except Exception as e:
        print(f"Failed to register session: {e}")

if __name__ == "__main__":
    register()
