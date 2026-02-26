import asyncio
from lighter import ApiClient, Configuration, OrderApi

async def main():
    try:
        # If no config is passed, it uses the SDK default host
        c = ApiClient()
        print("SDK Default Host:", c.configuration.host)
        o = OrderApi(c)
        res = await o.order_books()
        print("SDK success:", len(res))
    except Exception as e:
        print("SDK error:", type(e), e)
    finally:
        await c.close()

if __name__ == '__main__':
    asyncio.run(main())
