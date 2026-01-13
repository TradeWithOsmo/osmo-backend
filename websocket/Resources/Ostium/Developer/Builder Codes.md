# Builder Codes

Builder Fees provide a permissionless referral system that enables third-party integrators to earn revenue from trades they facilitate through the Ostium protocol. Any address can act as a builder without prior approval or registration.

### How It Works

Builder fees are optional parameters included when opening trades that allow integrators to specify:

* **`builder`** - The fee recipient address
* **`builderFee`** - The fee percentage (scaled by 1e6)

#### Key Characteristics

* **Charged at trade opening only** - Fees are deducted from the collateral when the trade is opened
* **Maximum fee cap** - Builder fees are capped at 0.5% (50 basis points) to protect users
* **Atomic transfer** - Fees are transferred atomically when the trade opens, with no accrual, claiming, or withdrawal step required
* **Permissionless** - Any address can act as a builder without prior approval or registration
* **Required Parameters** - Builder parameters must be provided but can be set to zero address (0x0) and zero fee if no builder fee is needed

### Using Builder Fees with the Python SDK

#### Basic Example with Builder Fee

```python
import asyncio
from ostium_python_sdk import OstiumSDK
from ostium_python_sdk.config import NetworkConfig

async def main():
    # Initialize SDK
    config = NetworkConfig.testnet()
    sdk = OstiumSDK(config, private_key, rpc_url, verbose=True)

    # Get current price
    latest_price, _, _ = await sdk.price.get_price("BTC", "USD")

    # Define trade parameters with builder fee
    trade_params = {
        'collateral': 300,
        'leverage': 50,
        'asset_type': 0,                    # BTC-USD
        'direction': True,                  # Long
        'order_type': 'MARKET',
        'builder_address': '0x_YOUR_EVM_ADDRESS',
        'builder_fee': 0.1                  # 0.1%
    }

    # Execute trade
    trade_result = sdk.ostium.perform_trade(trade_params, at_price=latest_price)

    print(f"Order ID: {trade_result['order_id']}")
    print(f"Transaction: {trade_result['receipt']['transactionHash'].hex()}")

if __name__ == "__main__":
    asyncio.run(main())
```

#### Trade Without Builder Fee

If you don't specify builder parameters, the SDK automatically uses default values (zero address and zero fee):

```python
trade_params = {
    'collateral': 100,
    'leverage': 50,
    'asset_type': 0,
    'direction': True,
    'order_type': 'MARKET'
    # No builder_address or builder_fee specified
}

trade_result = sdk.ostium.perform_trade(trade_params, at_price=latest_price)
```

### Direct Contract Interaction

#### Contract Interface

The `openTrade` function accepts a `BuilderFee` struct:

```solidity
struct BuilderFee {
    address builder;      // Fee recipient address
    uint32 builderFee;    // Fee percentage (scaled by 1e6)
}
```

#### Web3.py Example

```python
from web3 import Web3
from eth_account import Account

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(rpc_url))
account = Account.from_key(private_key)

# Contract setup
trading_contract = w3.eth.contract(
    address=trading_contract_address,
    abi=trading_abi
)

# Prepare trade struct
trade = {
    'collateral': 100000000,        # 100 USDC (scaled by 1e6)
    'openPrice': int(50000 * 1e18), # 50,000 USD (scaled by 1e18)
    'tp': 0,                         # Take profit (0 = none)
    'sl': 0,                         # Stop loss (0 = none)
    'trader': account.address,
    'leverage': 5000,                # 50x leverage (scaled by 1e2)
    'pairIndex': 0,                  # BTC-USD
    'index': 0,
    'buy': True                      # Long position
}

# Prepare builder fee struct
builder_fee = {
    'builder': '0x_YOUR_EVM_ADDRESS',
    'builderFee': 10000              # 0.1% (0.1 * 1e6 / 100)
}

# Slippage parameter
slippage = 200  # 2% (scaled by 1e2)

# Order type (0 = MARKET, 1 = LIMIT, 2 = STOP)
order_type = 0

# Build and send transaction
tx = trading_contract.functions.openTrade(
    trade,
    builder_fee,
    order_type,
    slippage
).build_transaction({
    'from': account.address,
    'nonce': w3.eth.get_transaction_count(account.address)
})

# Sign and send
signed_tx = w3.eth.account.sign_transaction(tx, private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

print(f"Transaction hash: {tx_hash.hex()}")
```

#### Without Builder Fee (Direct Contract Call)

To open a trade without builder fees, pass the zero address with zero fee:

```python
# Builder fee struct with no fee
builder_fee = {
    'builder': '0x0000000000000000000000000000000000000000',
    'builderFee': 0
}

tx = trading_contract.functions.openTrade(
    trade,
    builder_fee,
    order_type,
    slippage
).build_transaction({
    'from': account.address,
    'nonce': w3.eth.get_transaction_count(account.address)
})
```
