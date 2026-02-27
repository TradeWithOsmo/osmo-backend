import asyncio
from services.client_registry import get_exchange_client

async def probe(exchange, symbol):
    c = get_exchange_client(exchange)
    print(f"\n=== {exchange} / {symbol} ===", flush=True)
    if not c:
        print('no client', flush=True)
        return

    if hasattr(c, 'get_depth'):
        try:
            d = await c.get_depth(symbol)
            print('depth type:', type(d).__name__, flush=True)
            if isinstance(d, dict):
                print('depth keys:', list(d.keys())[:20], flush=True)
                b = d.get('bids', [])
                a = d.get('asks', [])
                print('bids len:', len(b), 'asks len:', len(a), flush=True)
                if b:
                    x = b[0]
                    print('bid0 type:', type(x).__name__, flush=True)
                    if isinstance(x, dict):
                        print('bid0 keys:', list(x.keys())[:20], flush=True)
                        print('bid0 sample:', {k: x.get(k) for k in list(x.keys())[:8]}, flush=True)
                    else:
                        print('bid0:', x, flush=True)
                if a:
                    x = a[0]
                    print('ask0 type:', type(x).__name__, flush=True)
                    if isinstance(x, dict):
                        print('ask0 keys:', list(x.keys())[:20], flush=True)
                        print('ask0 sample:', {k: x.get(k) for k in list(x.keys())[:8]}, flush=True)
                    else:
                        print('ask0:', x, flush=True)
        except Exception as e:
            print('get_depth err:', repr(e), flush=True)
    else:
        print('no get_depth', flush=True)

    if hasattr(c, 'get_recent_trades'):
        try:
            t = await c.get_recent_trades(symbol, limit=5)
            print('trades type:', type(t).__name__, flush=True)
            if isinstance(t, list):
                print('trades len:', len(t), flush=True)
                if t:
                    x = t[0]
                    print('trade0 type:', type(x).__name__, flush=True)
                    if isinstance(x, dict):
                        print('trade0 keys:', list(x.keys())[:25], flush=True)
                        print('trade0 sample:', {k: x.get(k) for k in list(x.keys())[:12]}, flush=True)
                    else:
                        print('trade0:', x, flush=True)
        except Exception as e:
            print('get_recent_trades err:', repr(e), flush=True)
    else:
        print('no get_recent_trades', flush=True)

async def main():
    await probe('aster', 'BTCUSDT')
    await probe('vest', 'BTC-PERP')
    await probe('lighter', 'BTC-USD')

asyncio.run(main())
