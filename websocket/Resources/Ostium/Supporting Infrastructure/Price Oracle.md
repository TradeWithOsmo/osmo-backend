# Price Oracle

1. In-house built Real World Asset feeds, with node and aggregator infrastructure operated by Stork Network
2. Chainlink Data Streams for crypto feeds.

## Real World Asset Oracle: Ostium x Stork

Ostium uses a pull-based RWA oracle system architected in-house from the ground up for the unique complexities of Real World Assets.&#x20;

The existence of out-of-market hours, future contract rolls, price gaps at market open, and more for RWAs meant secure, trust minimized, scalable price feeds – in particular for long-tail assets – could only be achieved through a custom oracle solution. &#x20;

Data partnerships and sourcing, market hours data, and asset-specific node price feed aggregation logic are built by the development company behind the Ostium Protocol.&#x20;

A majority of node infrastructure is then managed and operated by Stork & their decentralized network of nodes.

Unlike cryptocurrencies which trade continuously, real-world assets (RWAs) such as commodities and forex pairs operate on defined weekly trading schedules. You can access these schedules through the [API & SDK documentation section](https://ostium-labs.gitbook.io/ostium-docs/api-and-sdk) or by clicking the colored dot in the top-left corner of the Trading View chart, adjacent to the asset name.&#x20;

<figure><img src="https://1263702948-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FCEDPLHGTrrpP1i2dbe3d%2Fuploads%2Fu7Q550VSkjudG999hPj6%2FTV-Screenshot%202025-03-12%20at%2014.54.13.png?alt=media&#x26;token=a4fdc209-32b3-48d7-8abf-bab85b8bf52d" alt=""><figcaption></figcaption></figure>

Although orders cannot be executed during market closures, you may still place Limit and Stop orders when markets are closed. These orders will automatically execute when markets reopen and the specified price conditions are met. Note that Market orders cannot be placed during non-trading hours.

Supplementing the standard weekly schedule, feeds include holiday session data that specifies dates when markets are closed for trading.

## Crypto Oracle: Chainlink Data Streams

Ostium uses Chainlink [Data Streams](https://docs.chain.link/data-streams) for its crypto feeds. Chainlink's reliability and track record of security are paramount to ensuring secure feeds for high-volatility crypto assets.

## Pull vs. Push Oracles

Because of the costs involved in writing prices onchain for high-throughput (1sec price updates across dozens of assets) applications, prices in a pull-based system are only written onchain when explicitly required for trade execution.&#x20;

{% hint style="info" %}
To ensure appropriate pricing, market open/close data and bid/ask prices (order book depth) are passed directly into the price report's metadata, and consumed programmatically by Ostium's smart contracts to eliminate human intervention in spread setting and market hour adaptations.
{% endhint %}

See Stork [documentation](https://docs.stork.network/) for more details.

***Further details on our unique in-house oracle architecture coming soon.***
