import asyncio
import httpx
import websockets
import json
import time

async def test_symbol(exchange, symbol, base_ws):
    url = f"{base_ws}/{exchange}/{symbol}"
    # print(f"  Testing {url}...")
    try:
        async with websockets.connect(url, open_timeout=2) as websocket:
            # Wait for first message
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=3)
                # Successful connection and data received
                return True, "Data received"
            except asyncio.TimeoutError:
                return True, "Connected, but no data (Timeout)"
    except Exception as e:
        return False, str(e)

async def main():
    base_ws = "ws://127.0.0.1:8000/ws"
    base_api = "http://127.0.0.1:8000/api/markets/"
    
    print("Pre-fetching markets...")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(base_api)
            markets = resp.json().get("markets", [])
    except Exception as e:
        print(f"Failed to fetch markets: {e}")
        return

    exchanges = ["hyperliquid", "ostium", "aster", "vest", "avantis", "lighter"]
    
    print(f"{'Exchange':<15} | {'Status':<10} | {'Details'}")
    print("-" * 60)
    
    for exc in exchanges:
        exc_syms = [m.get("symbol") for m in markets if m.get("source") == exc]
        if not exc_syms:
            print(f"{exc:<15} | {'SKIP':<10} | No symbols found in markets")
            continue
            
        success_count = 0
        total_tried = min(5, len(exc_syms))
        details = ""
        
        for i in range(total_tried):
            sym = exc_syms[i]
            # print(f"    {sym}...", end="", flush=True)
            ok, msg = await test_symbol(exc, sym, base_ws)
            if ok:
                success_count += 1
            else:
                details = msg # Capture last error
        
        status = "OK" if success_count == total_tried else f"PARTIAL ({success_count}/{total_tried})"
        if success_count == 0:
            status = "FAILED"
            
        print(f"{exc:<15} | {status:<10} | {details or 'All tested symbols working'}")

if __name__ == "__main__":
    asyncio.run(main())
