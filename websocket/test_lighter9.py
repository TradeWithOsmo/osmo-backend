import asyncio
from lighter import ApiClient, OrderApi, OrderbookApi

async def main():
    try:
        c = ApiClient()
        o = OrderApi(c)
        methods = [m for m in dir(o) if not m.startswith('_')]
        print("OrderApi methods:")
        for m in methods:
            if 'book' in m or 'depth' in m:
                print("  ->", m)
    except Exception as e:
        print("Error OrderApi:", e)

    try:
        c = ApiClient()
        ob = OrderbookApi(c)
        methods = [m for m in dir(ob) if not m.startswith('_')]
        print("OrderbookApi methods:")
        for m in methods:
            if 'book' in m or 'depth' in m:
                print("  ->", m)
    except Exception as e:
        print("Error OrderbookApi:", e)

if __name__ == '__main__':
    asyncio.run(main())
