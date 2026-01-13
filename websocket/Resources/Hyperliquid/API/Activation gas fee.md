# Activation gas fee

New HyperCore accounts require 1 quote token (e.g., 1 USDC, 1 USDT, or 1 USDH) of fees for the first transaction which has the new account as destination address. This applies regardless of the asset being transfered to the new account.&#x20;

Unactivated accounts cannot send CoreWriter actions. Contract deployers who do not want this one-time behavior could manually send an activation transaction to the EVM contract address on HyperCore.&#x20;
