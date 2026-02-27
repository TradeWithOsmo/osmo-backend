import asyncio
from lighter import ApiClient, OrderApi

async def main():
    try:
        c = ApiClient()
        o = OrderApi(c)
        methods = [m for m in dir(o) if not m.startswith('_')]
        print("Methods on OrderApi:", methods)
        
        # Test if we can get an orderbook for market_id 16 (SUI)
        if 'orderbook' in methods:
            ob = await o.orderbook(16)
            print("Orderbook type:", type(ob))
        elif 'get_orderbook' in methods:
            ob = await o.get_orderbook(16)
            print("Orderbook type:", type(ob))
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
