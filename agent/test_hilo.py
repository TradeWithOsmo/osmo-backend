import asyncio
import os
import sys

# Add the current directory to sys.path to ensure 'agent' can be imported
sys.path.append(os.getcwd())

async def test():
    try:
        from agent.Tools.data.market import get_high_low_levels
        res = await get_high_low_levels('BTC-USD', timeframe='1H', lookback=7)
        print("RESULT_KEYS:", list(res.keys()))
        print("RESULT_DATA:", res)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
