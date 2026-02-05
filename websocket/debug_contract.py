from connectors.web3_arbitrum.connector import web3_connector
import sys

try:
    print("Attempting to load OrderRouter...")
    contract = web3_connector.get_contract("OrderRouter")
    print(f"Success! Address: {contract.address}")
except Exception as e:
    print(f"Failed: {e}")
    import traceback
    traceback.print_exc()
