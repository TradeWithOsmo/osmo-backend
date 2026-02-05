from web3 import Web3
import sys

sys.path.append('/app')
from config import settings

RPC_URL = settings.ARBITRUM_RPC_URL
ORDER_ROUTER_ADDRESS = settings.ORDER_ROUTER_ADDRESS

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def check():
    c = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=[{'inputs':[{'name':'symbol','type':'string'}],'name':'getOraclePrice','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'}])
    price = c.functions.getOraclePrice('BTC-USD').call()
    print(f"Price BTC-USD: {price}")
    
    # Also check latestPrices mapping directly to see if it's there
    # latestPrices is a mapping(string => uint256) at slot? 
    # Actually just call the public getter
    c2 = w3.eth.contract(address=Web3.to_checksum_address(ORDER_ROUTER_ADDRESS), abi=[{'inputs':[{'name':'','type':'string'}],'name':'latestPrices','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'}])
    lp = c2.functions.latestPrices('BTC-USD').call()
    print(f"LatestPrice BTC-USD: {lp}")

if __name__ == "__main__":
    check()
