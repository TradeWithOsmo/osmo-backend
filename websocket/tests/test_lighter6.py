import asyncio
from lighter import ApiClient, OrderApi

async def main():
    try:
        c = ApiClient()
        o = OrderApi(c)
        res = getattr(await o.order_books(), 'order_books')
        
        first = res[0]
        # Since it might be a Pydantic model or similar struct, use __dict__
        print(first.__dict__ if hasattr(first, '__dict__') else first)
        
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
