import asyncio
import os
import sys
import json

# Ensure backend root is in PYTHONPATH
sys.path.append(r"d:\WorkingSpace\backend")

# Try to find the correct import path
try:
    from agent.Tools.data.analysis import get_technical_analysis
    from agent.Tools.data.tradingview import get_active_indicators
except ImportError:
    # Try with backend prefix
    from backend.agent.Tools.data.analysis import get_technical_analysis
    from backend.agent.Tools.data.tradingview import get_active_indicators

async def run_test():
    print("--- [TEST 1] get_technical_analysis ---")
    try:
        # This will call http://localhost:8000/api/connectors/analysis/technical/BTC-USD
        # Let's see what it returns. Ensure the backend is running!
        # If it's NOT running, it will error.
        res1 = await get_technical_analysis(symbol="BTC-USD", timeframe="1H", asset_type="crypto")
        print(f"Result:\n{json.dumps(res1, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- [TEST 2] get_active_indicators ---")
    try:
        # Passing tool_states to see the fallback
        tool_states = {
            "market_symbol": "BTC-USD",
            "market_timeframe": "1H",
            "market_active_indicators": ["RSI", "SMA"]
        }
        res2 = await get_active_indicators(symbol="BTC-USD", timeframe="1H", tool_states=tool_states)
        print(f"Result:\n{json.dumps(res2, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
