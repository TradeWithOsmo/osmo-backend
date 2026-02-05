from web3 import Web3
import os
import sys

# Add backend and websocket to path
backend_path = "d:/WorkingSpace/backend"
sys.path.append(backend_path)
sys.path.append(os.path.join(backend_path, "websocket"))

from config import settings

def test_rpc():
    print(f"Testing RPC: {settings.ARBITRUM_RPC_URL}")
    w3 = Web3(Web3.HTTPProvider(settings.ARBITRUM_RPC_URL))
    if w3.is_connected():
        print(f"Connected! Current block: {w3.eth.block_number}")
    else:
        print("Failed to connect to primary RPC.")
        
    print(f"Testing Backup RPC: {settings.ARBITRUM_BACKUP_RPC_URL}")
    w3_backup = Web3(Web3.HTTPProvider(settings.ARBITRUM_BACKUP_RPC_URL))
    if w3_backup.is_connected():
        print(f"Connected to backup! Current block: {w3_backup.eth.block_number}")
    else:
        print("Failed to connect to backup RPC.")

if __name__ == "__main__":
    test_rpc()
