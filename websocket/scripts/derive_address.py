from eth_account import Account
import os

def get_address(pk):
    if not pk: return None
    if pk.startswith("0x"): pk = pk[2:]
    return Account.from_key(pk).address

# Example pk from your .env
pk = "0x40ed53fc84e04e95cecb450ebd7984b11da40efd90218d09d6506ee274375d0b"
print(f"Address: {get_address(pk)}")
