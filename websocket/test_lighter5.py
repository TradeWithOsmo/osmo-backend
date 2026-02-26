import asyncio
from lighter import ApiClient, OrderApi

async def main():
    try:
        c = ApiClient()
        o = OrderApi(c)
        res = await o.order_books()
        print("SDK success:")
        print("Type:", type(res))
        print("Dir:", dir(res))
        
        # usually there is a typical property like `order_books` or similar inside
        for attr in ['data', 'order_books', 'markets', 'books']:
            if hasattr(res, attr):
                val = getattr(res, attr)
                print(f"Found {attr}: {len(val) if hasattr(val, '__len__') else 'no len'}")
                if val:
                    print("First item attrs:", dir(val[0]))
                    print("Market ID:", getattr(val[0], 'id', None) or getattr(val[0], 'market_id', None))
                    print("Base asset:", getattr(val[0], 'base_asset', None) or getattr(val[0], 'base', None) or getattr(val[0], 'base_asset_name', None))
                    
    except Exception as e:
        print("SDK error:", type(e), e)
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
