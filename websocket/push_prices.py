from web3 import Web3
import sys
import time

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
ORDER_ROUTER_ADDRESS = settings.ORDER_ROUTER_ADDRESS
TREASURY_PK = settings.TREASURY_PRIVATE_KEY

w3 = Web3(Web3.HTTPProvider(RPC_URL))
account = w3.eth.account.from_key(TREASURY_PK)

ROUTER_ABI = [
    {
        "inputs": [
            {"name": "symbols", "type": "string[]"},
            {"name": "prices", "type": "uint256[]"}
        ],
        "name": "updatePrices",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def push():
    contract = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=ROUTER_ABI)
    
    symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    # Mock prices ($100k, $3k, $100)
    prices = [100000 * 1000000, 3000 * 1000000, 100 * 1000000]
    
    print(f"Pushing prices {symbols} from {account.address}...")
    
    tx = contract.functions.updatePrices(symbols, prices).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 500000,
        'gasPrice': int(w3.eth.gas_price * 1.5),
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, TREASURY_PK)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction sent: {tx_hash.hex()}")
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print("Price push successful!")

if __name__ == "__main__":
    push()
