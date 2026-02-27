from lighter import ApiClient, OrderApi
import asyncio

async def check_trades():
    api_client = ApiClient()
    try:
        order_api = OrderApi(api_client)
        resp = await order_api.recent_trades(market_id=1, limit=10)
        trades = resp.trades if hasattr(resp, "trades") else []
        print(f"Found {len(trades)} recent trades")
        if trades:
            t = trades[0].dict() if hasattr(trades[0], "dict") else trades[0].__dict__
            print("First trade keys:", list(t.keys()))
            print("Values:", {k: t[k] for k in ['price', 'amount', 'timestamp', 'side'] if k in t})
    finally:
        await api_client.close()

if __name__ == "__main__":
    asyncio.run(check_trades())
