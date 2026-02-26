from lighter import ApiClient, OrderApi
import asyncio

async def check():
    c = ApiClient()
    r = await OrderApi(c).order_book_details(market_id=1)
    ask = r.order_book.asks[0]
    print("ASK TYPE:", type(ask))
    print("ASK DICT:", ask.dict())
    await c.close()

asyncio.run(check())
