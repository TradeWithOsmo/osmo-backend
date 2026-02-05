from web3 import Web3
from eth_account import Account
import sys

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
ORDER_ROUTER_ADDRESS = settings.ORDER_ROUTER_ADDRESS
TERTIARY_PK = "0xbc8bb576dfcbb99056999324862c80ce10d73e37f8d6d781a4861d5ef5f1dc99"
TREASURY_ADDRESS = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"

w3 = Web3(Web3.HTTPProvider(RPC_URL))
admin_account = Account.from_key(TERTIARY_PK)

ROUTER_ABI = [
    {'inputs':[],'name':'OPERATOR_ROLE','outputs':[{'name':'','type':'bytes32'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'role','type':'bytes32'},{'name':'account','type':'address'}],'name':'grantRole','outputs':[],'stateMutability':'nonpayable','type':'function'}
]

def grant():
    contract = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=ROUTER_ABI)
    
    role = contract.functions.OPERATOR_ROLE().call()
    
    print(f"Granting OPERATOR_ROLE to Treasury {TREASURY_ADDRESS} using Admin {admin_account.address}...")
    
    tx = contract.functions.grantRole(role, Web3.to_checksum_address(TREASURY_ADDRESS)).build_transaction({
        'from': admin_account.address,
        'nonce': w3.eth.get_transaction_count(admin_account.address),
        'gas': 500000,
        'gasPrice': w3.eth.gas_price,
        'chainId': w3.eth.chain_id
    })
    
    signed_tx = w3.eth.account.sign_transaction(tx, TERTIARY_PK)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Transaction sent: {tx_hash.hex()}")
    w3.eth.wait_for_transaction_receipt(tx_hash)
    print("Role Grant successful!")

if __name__ == "__main__":
    grant()
