import asyncio
import websockets
import json

async def test_ws(url):
    print(f"Testing {url}...")
    try:
        async with websockets.connect(url, open_timeout=5) as websocket:
            print(f"  [OK] Connected to {url}")
            # Wait for initial message
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=2)
                data = json.loads(msg)
                # Some feeds might send a welcome message or price data
                msg_type = data.get('type')
                msg_data = data.get('data')
                print(f"  [RECEIVED] {msg_type} (Sample: {str(msg_data)[:50]}...)")
            except asyncio.TimeoutError:
                print(f"  [TIMEOUT] No initial message received")
            return True
    except Exception as e:
        print(f"  [ERROR] Failed to connect to {url}: {e}")
        return False

async def main():
    # Use localhost:8000 since uvicorn is running on 0.0.0.0:8000
    base_ws = "ws://localhost:8000/ws"
    tests = [
        f"{base_ws}/hyperliquid/BTC-USD",
        f"{base_ws}/ostium/ETH-USD",
        f"{base_ws}/aster/RECALLUSDT",
        f"{base_ws}/vest/MSI-USD-PERP",
        f"{base_ws}/avantis/ETH-USD",
        f"{base_ws}/lighter/ETH-USD",
    ]
    
    print("Starting WebSocket connectivity tests...")
    print("=" * 40)
    for url in tests:
        await test_ws(url)
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
