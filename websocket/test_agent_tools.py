"""
Test agent tools: setup_trade, place_order, then check_order & get_positions
"""
import asyncio
import json
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/agent')

async def main():
    USER = "0x1234567890123456789012345678901234567890"
    TOOL_STATES = {
        "user_address": USER,
        "execution": True,
        "policy_mode": "auto_exec",
        "execution_exchange": "simulation",
    }

    from agent.Orchestrator.execution_adapter import ExecutionAdapter

    # 1. Place order (this is what the agent tool does when auto_exec)
    print("=" * 60)
    print("TEST: place_order (BTC-USD BUY $50 3x simulation)")
    print("=" * 60)
    result = await ExecutionAdapter.place_order(
        user_address=USER,
        symbol="BTC-USD",
        side="buy",
        amount_usd=50,
        leverage=3,
        order_type="market",
        exchange="simulation",
    )
    print(json.dumps(result, indent=2, default=str))

    # 2. Check order history
    print("\n" + "=" * 60)
    print("TEST: get_user_orders")
    print("=" * 60)
    from services.order_service import OrderService
    svc = OrderService()
    orders = await svc.get_user_orders(USER, exchange="simulation")
    print(f"Total orders: {len(orders)}")
    for o in orders[-3:]:
        print(f"  - {o.get('side')} {o.get('symbol')} status={o.get('status')} size=${o.get('notional_usd')}")

    # 3. Check positions
    print("\n" + "=" * 60)
    print("TEST: get_positions")
    print("=" * 60)
    from agent.Tools.data.trade import get_positions
    pos_result = await get_positions(user_address=USER, exchange="simulation")
    positions = pos_result.get("positions", [])
    print(f"Total open positions: {len(positions)}")
    for p in positions:
        print(f"  - {p.get('side')} {p.get('symbol')} size={p.get('size'):.6f} BTC entry={p.get('entry_price')} margin=${p.get('margin_used')} exchange={p.get('exchange')}")

asyncio.run(main())
