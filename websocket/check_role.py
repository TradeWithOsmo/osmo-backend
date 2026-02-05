from web3 import Web3
from eth_account import Account
import sys

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
ORDER_ROUTER_ADDRESS = settings.ORDER_ROUTER_ADDRESS
TREASURY_ADDRESS = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def check():
    c = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=[
        {'inputs':[],'name':'OPERATOR_ROLE','outputs':[{'name':'','type':'bytes32'}],'stateMutability':'view','type':'function'},
        {'inputs':[{'name':'role','type':'bytes32'},{'name':'account','type':'address'}],'name':'hasRole','outputs':[{'name':'','type':'bool'}],'stateMutability':'view','type':'function'}
    ])
    addresses = {
        "Treasury": "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C",
        "Secondary": Account.from_key("0x7a389c308788fa0dcede385cc23ea71f90c9a6ac412321197e551ba83574f741").address,
        "Tertiary": Account.from_key("0xbc8bb576dfcbb99056999324862c80ce10d73e37f8d6d781a4861d5ef5f1dc99").address
    }
    
    role = c.functions.OPERATOR_ROLE().call()
    admin_role = "0x0000000000000000000000000000000000000000000000000000000000000000"
    
    for name, addr in addresses.items():
        has_operator = c.functions.hasRole(role, Web3.to_checksum_address(addr)).call()
        has_admin = c.functions.hasRole(admin_role, Web3.to_checksum_address(addr)).call()
        print(f"{name} ({addr}) - OPERATOR: {has_operator}, ADMIN: {has_admin}")

if __name__ == "__main__":
    check()
