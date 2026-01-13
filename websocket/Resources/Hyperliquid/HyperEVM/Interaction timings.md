# Interaction timings

## Transfer Timing

Transfers from HyperCore to HyperEVM are queued on the L1 until the next HyperEVM block. Transfers from HyperEVM to HyperCore happen in the same L1 block as the HyperEVM block, immediately after the HyperEVM block is built.

## Timing within a HyperEVM block

On an L1 block that produces a HyperEVM block:

1. L1 block is built
2. EVM block is built
3. EVM -> Core transfers are processed&#x20;
4. CoreWriter actions are processed&#x20;

Note that the account performing the CoreWriter action must exist on HyperCore before the EVM block is built. An EVM -> Core transfer to initialize the account in the same block will still result in the CoreWriter action being rejected.
