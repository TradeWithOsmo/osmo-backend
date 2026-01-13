# Overview

As mentioned in the Ostium Trading Engine [section](https://ostium-labs.gitbook.io/ostium-docs/ostium-trading-engine), **Off-Chain Services** are one of Ostium's three pillars. Those include a pull oracle and automation services operated by partner networks to fetch asset prices and trigger automated orders (e.g., liquidations, limit orders).

*Any high-speed perp DEX needs off-chain infrastructure to support it, custom-built in this case by the development company behind the Ostium Protocol to service the unique complexities of traditional asset markets (commodities, FX, indices and more). However, in the spirit of disintermediation and maximal decentralization, Ostium ensures minimal operational involvement through partner network operation.*

## Infrastructure Partners

Ostium relies on complex external systems requiring near-perfect uptime and substantial redundancy. Partnerships with two core networks facilitate this:

* **Oracle**: [Stork](https://www.stork.network/) nodes for Ostium's in-house RWA feeds, [Chainlink](https://docs.chain.link/data-streams) for crypto feeds
* **Automated Keeper System**:[ Gelato](https://gelato.network)

The following items represent the up-stream interactions of this infrastructure before interacting with Ostium's smart contracts:

1. **Data Providers**: multiple exchanges offer real-time price feeds, ensuring that traders on our platform always have access to the latest market prices for every listed trading pair, delivering accuracy and reliability in every trade;
2. **Stork**: Oracle price services, developed by Ostium Labs and operated by partners, optimizing decentralization by distributing responsibilities while maintaining secure and reliable price feeds;
3. **Gelato**: Automation services monitor onchain price requests and respond by providing the requested price report onchain. Additionally, Gelato automates the conditional orders for SL, TP, Liquidation and Limit;
4. **Ostium Protocol:** Our smart contracts ensure that all open and close orders are executed using the latest price, guaranteeing up-to-date accuracy in every trade.
