from web3 import Web3
import sys

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
ORDER_ROUTER_ADDRESS = settings.ORDER_ROUTER_ADDRESS
USER_ADDRESS = "0xC65870884989F6748aF9822f17b2758A48d97B79"
TREASURY_ADDRESS = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

ORDER_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    { "name": "user", "type": "address" },
                    { "name": "symbol", "type": "string" },
                    { "name": "side", "type": "uint8" },
                    { "name": "orderType", "type": "uint8" },
                    { "name": "amountUsd", "type": "uint256" },
                    { "name": "leverage", "type": "uint8" },
                    { "name": "reduceOnly", "type": "bool" },
                    { "name": "postOnly", "type": "bool" },
                    { "name": "triggerCondition", "type": "uint8" },
                    { "name": "price", "type": "uint256" },
                    { "name": "stopPrice", "type": "uint256" },
                    { "name": "timeInForce", "type": "uint256" }
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "placeOrder",
        "outputs": [{ "name": "orderId", "type": "bytes32" }],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def check_revert():
    contract = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=ORDER_ROUTER_ABI)
    
    tuple_params = {
        "user": Web3.to_checksum_address(USER_ADDRESS),
        "symbol": "BTC-USD",
        "side": 0, # Buy
        "orderType": 0, # Market
        "amountUsd": 11 * 1000000, # $11
        "leverage": 10,
        "reduceOnly": False,
        "postOnly": False,
        "triggerCondition": 0,
        "price": 0,
        "stopPrice": 0,
        "timeInForce": 0
    }
    
    try:
        print(f"Simulating placeOrder as USER {USER_ADDRESS}...")
        contract.functions.placeOrder(tuple_params).call({'from': Web3.to_checksum_address(USER_ADDRESS)})
        print("Simulation successful (as USER)!")
    except Exception as e:
        print(f"Revert error (as USER): {e}")

    try:
        print(f"Simulating placeOrder as TREASURY {TREASURY_ADDRESS} (Delegate)...")
        contract.functions.placeOrder(tuple_params).call({'from': Web3.to_checksum_address(TREASURY_ADDRESS)})
        print("Simulation successful (as TREASURY)!")
    except Exception as e:
        print(f"Revert error (as TREASURY): {e}")

if __name__ == "__main__":
    check_revert()
