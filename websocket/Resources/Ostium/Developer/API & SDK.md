# API & SDK

Ostium Labs offers an SDK built in Python (v3.10) that allows for reading of the platform's state: a list of trading pairs, rolling fees, and open interest caps for each. It also allows for placing of new Orders (Market, Limit and Stop), reading their state, such as open PnL and fees paid, as well as editing them and deleting them. It also allows for reading the entire history of orders. All of this can be done in an entirely programatic way by using python as the programing language.

Ostium also provides a REST endpoint that serves the purpose of exposing platform metrics and state in an easy manner for anyone to read.

* Reading latest prices for all feeds:

  <pre><code><strong>curl  -X 'GET' 'https://metadata-backend.ostium.io/PricePublish/latest-prices' 
  </strong> -H 'Content-Type: application/json'  | jq
  </code></pre>

  This is useful when placing an order on the platform, allowing a user to see the latest price before placing a trade.
* Reading latest price for specific feed:

  <pre><code><strong>curl  -X 'GET' 'https://metadata-backend.ostium.io/PricePublish/latest-price?asset=EURUSD' 
  </strong> -H 'Content-Type: application/json'  | jq
  </code></pre>

  This is useful when placing an order on the platform, allowing a user to see the latest price before placing a trade.
* Reading the trading hours for RWA assets:

```
curl "https://metadata-backend.ostium.io/trading-hours/asset-schedule?asset=EURUSD" | jq
```

This endpoint returns a response showing the trading pair trading schedule and the current trading status, in a human readable format, e.g:

```
{
  "timezone": "America/New_York",
  "openingHours": [
    "Mo-Fr 04:00-17:00,18:00-20:00"
  ],
  "nextPublicHoliday": "2025-04-18",
  "isOpenNow": false
}
```

* Reading liquidity providers' exposure:&#x20;

<pre data-overflow="wrap"><code><strong>curl -X POST https://metadata-backend.ostium.io/vault/lp-exposure  -H 
</strong>"Content-Type: application/json" -d 
'{"address": "0x605920C7A289af4891C824602ad0E3449F8676B9"}'  | jq
</code></pre>

If you have deposited liquidity to the vault, you can use the above REST end-point by supplying your depositing address to retrieve insights into your exposure to different assets based on the current imbalance state of the platform.

## Dune Analytics

Below is the Dune analytics dashboard showing the platform's main metrics:

{% embed url="<https://dune.com/ostium_app/stats>" %}

## Python SDK

Ostium's PyPi module is located [here](https://pypi.org/project/ostium-python-sdk). The codebase for the SDK is publicly available [here](https://github.com/0xOstium/ostium-python-sdk).

#### Installing the SDK

```
pip install ostium-python-sdk
```

If you wish to contribute code or report of any issue, please contact us via Github repository page.

The SDK works both on mainnet (Arbitrum One) and on testnet (Arbitrum Sepolia).&#x20;

In order to instantiate the SDK you merely need a RPC URL for one of the above networks you wish to interact with. You can obtain an RPC freely from Alchemy; consult the README for more information.

In order to place trades you need to instantiate the SDK with a private key or to supply a private key to relevant methods. Consult the README for more information and basic related security issues.

To place trades on testnet, you must obtain testnet USDC, which you can do from our faucet. The SDK has a special set of actions that enable this.&#x20;

To start performing any write operation (e.g. interact with the platform on testnet or mainnet using the instantiated private key), you must have some native token for gas. For Arbitrum Sepolia gas, you may use [Alchemy's Arbitrum Sepolia Faucet](https://www.alchemy.com/faucets/arbitrum-sepolia).
