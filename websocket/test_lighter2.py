import asyncio
from lighter import ApiClient, Configuration, OrderApi

async def main():
    try:
        # Original Elliot.ai domains seem blocked or down for HTTP
        c = ApiClient(Configuration(host='https://api.lighter.xyz'))
        o = OrderApi(c)
        res = await o.order_books()
        print("SDK success:", len(res))
        if res:
            # Let's inspect the first item
            first = res[0]
            print("First item attrs:", dir(first))
            # Try to get market properties to see how they map
            print("symbol/base:", getattr(first, 'base_asset_name', None), getattr(first, 'base_asset', None), getattr(first, 'base', None))
    except Exception as e:
        print("SDK error:", type(e), e)
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
