"""
Test size_pct feature: place order using percentage of balance.
"""
import asyncio, json, sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/agent')

async def main():
    USER = "0xdeadbeef00000000000000000000000000000001"

    # Simulate tool_states injected by agent router at runtime
    # (normally free_collateral_usd is fetched from portfolio service)
    TOOL_STATES_WITH_BALANCE = {
        "user_address": USER,
        "execution": True,
        "policy_mode": "auto_exec",
        "execution_exchange": "simulation",
        "free_collateral_usd": 1000.0,   # user has $1000 free
        "trading_balance_usd": 1000.0,
    }

    from agent.Tools.trade_execution import place_order

    print("=" * 60)
    print("TEST 1: size_pct=0.25 (25% of $1000 = $250)")
    print("=" * 60)
    r = await place_order(
        symbol="BTC-USD",
        side="buy",
        size_pct=0.25,
        leverage=5,
        tool_states=TOOL_STATES_WITH_BALANCE,
    )
    print(json.dumps(r, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TEST 2: size_pct=0.5 (50% of $1000 = $500)")
    print("=" * 60)
    r2 = await place_order(
        symbol="ETH-USD",
        side="buy",
        size_pct=0.5,
        leverage=3,
        tool_states=TOOL_STATES_WITH_BALANCE,
    )
    print(json.dumps(r2, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TEST 3: size_pct=1.0 (100% of $1000 = $1000)")
    print("=" * 60)
    r3 = await place_order(
        symbol="BTC-USD",
        side="sell",
        size_pct=1.0,
        leverage=2,
        tool_states=TOOL_STATES_WITH_BALANCE,
    )
    print(json.dumps(r3, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TEST 4: no balance in tool_states → should error")
    print("=" * 60)
    r4 = await place_order(
        symbol="BTC-USD",
        side="buy",
        size_pct=0.5,
        tool_states={"user_address": USER, "execution": True, "policy_mode": "auto_exec"},
    )
    print(json.dumps(r4, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TEST 5: explicit amount_usd still works")
    print("=" * 60)
    r5 = await place_order(
        symbol="BTC-USD",
        side="buy",
        amount_usd=75,
        leverage=10,
        tool_states=TOOL_STATES_WITH_BALANCE,
    )
    print(json.dumps(r5, indent=2, default=str))

asyncio.run(main())
