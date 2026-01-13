# Automations

## Gelato Functions

Gelato functions are an Automation Keeper System that both listens to price requests emitted onchain and monitors existing open trades for conditions necessary to trigger automated orders (liquidations, stop loss, take profit, limit orders).

*High-leverage trading requires both a low-latency Oracle and an Automation Keeper System to ensure stellar UX and secure trading.*

Gelato functions are programmed to trigger the following actions:

* Limit Orders
* Stop Limit Orders
* Take Profits
* Stop Losses
* Liquidations
* Price Request

&#x20;See Gelato functions [documentation](https://docs.gelato.network/web3-services/web3-functions/understanding-web3-functions) for more details.

#### Gelato Dedicated Message Forwarder Contracts

The Gelato Message Forwarder is a dedicated contract responsible for executing take profit (TP), stop loss (SL), liquidations (LIQ), and limit orders. It also responds to price requests from the trading contracts by calling the appropriate callbacks, finally triggering the automated withdrawals and further requests. This contract is the only address authorized by our trading and callback contracts to perform these actions. It is maintained by Gelato and outside of our direct control.

* **Testnet (Arbitrum Sepolia)**: `0xad42C5dA19B8D3f8C20847cB5A1A2DEb502B5D46`
* **Mainnet (Arbitrum)**: `0x6297ce1A61C2C8a72BfB0DE957F6B1cF0413141e`
