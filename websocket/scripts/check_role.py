import asyncio
import os
import sys

# Ensure app is in path
sys.path.append("/app")

from web3 import Web3
try:
    from config import settings
    from connectors.web3_arbitrum.connector import web3_connector
except ImportError:
    from websocket.config import settings
    from websocket.connectors.web3_arbitrum.connector import web3_connector

async def t():
    try:
        w3 = web3_connector.w3
        ai_vault = web3_connector.get_contract("AIVault")
        signer_address = "0x464BF4046f2c71CbB67483E2Ff23640D21199A1C"
        
        function_names = {
            entry.get("name")
            for entry in (ai_vault.abi or [])
            if isinstance(entry, dict) and entry.get("type") == "function"
        }
        print(f"HAS deductFeeAmountByUser: {'deductFeeAmountByUser' in function_names}")
        print(f"HAS deductFeeAmount: {'deductFeeAmount' in function_names}")
        
        operator_role = await asyncio.to_thread(ai_vault.functions.OPERATOR_ROLE().call)
        print(f"OPERATOR_ROLE: {operator_role.hex() if isinstance(operator_role, (bytes, bytearray)) else operator_role}")
        
        has_role = await asyncio.to_thread(
            ai_vault.functions.hasRole(
                operator_role,
                Web3.to_checksum_address(signer_address),
            ).call
        )
        print(f"ADDRESS {signer_address} HAS_ROLE: {has_role}")
        
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == '__main__':
    asyncio.run(t())
