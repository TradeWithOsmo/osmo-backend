from web3 import Web3
import sys

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
SKM_ADDRESS = settings.SESSION_KEY_MANAGER_ADDRESS

USER = "0xC65870884989F6748aF9822f17b2758A48d97B79"
AGENT = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C" # Treasury

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def check():
    c = w3.eth.contract(address=Web3.to_checksum_address(SKM_ADDRESS), abi=[
        {'inputs':[{'name':'user','type':'address'},{'name':'agent','type':'address'}],'name':'validateSessionKey','outputs':[{'name':'','type':'bool'}],'stateMutability':'view','type':'function'}
    ])
    is_valid = c.functions.validateSessionKey(
        Web3.to_checksum_address(USER),
        Web3.to_checksum_address(AGENT)
    ).call()
    print(f"Session Key for USER {USER} using AGENT {AGENT} is VALID: {is_valid}")

if __name__ == "__main__":
    check()
