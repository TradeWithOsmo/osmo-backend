"""
Test Script for AI Agent Data Tools
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from backend.agent.Tools.data import market, analysis, analytics, web, tradingview, memory, knowledge


async def _exercise_market_tools():
    """Test Market Data Tools (Granular)"""
    print("\n[TEST] Testing Market Tools...")
    
    # 1. Hyperliquid (Crypto) - Price & Stats
    print("  > [Hyperliquid] get_price('BTC')")
    try:
        res = await market.get_price("BTC", asset_type="crypto")
        print(f"    Result: {str(res)[:100]}...")
    except Exception as e:
        print(f"    Error: {e}")
        
    # 2. Ostium (RWA) - Price (Mock/Real if available)
    print("  > [Ostium] get_price('EURUSD')")
    try:
        # Note: 'EURUSD' or specific ID depends on Ostium availability in dev env
        res = await market.get_price("EURUSD", asset_type="rwa")
        print(f"    Result: {str(res)[:100]}...")
    except Exception as e:
        print(f"    Error: {e}")

    # 3. Funding Rate (Backend Required)
    print("  > [Hyperliquid] get_funding_rate('BTC')")
    try:
        res = await market.get_funding_rate("BTC")
        print(f"    Result: {str(res)[:100]}...")
    except Exception as e:
        print(f"    Error: {e}")

    # 4. Orderbook/Depth (Backend Required for Liquidity)
    print("  > [Hyperliquid] get_orderbook('BTC')")
    try:
        res = await market.get_orderbook("BTC")
        # Truncate large orderbook data
        print(f"    Result: {str(res)[:100]}...")
    except Exception as e:
        print(f"    Error: {e}")
        
    # 5. OHLCV Candles (Raw Data)
    print("  > [Combined] get_candles('BTC', timeframe='1H')")
    try:
        res = await market.get_candles("BTC", timeframe="1H", limit=5)
        print(f"    Result: {str(res)[:150]}...")
    except Exception as e:
        print(f"    Error: {e}")

async def _exercise_analytics_tools():
    """Test Analytics (Whale/On-Chain)"""
    print("\n[TEST] Testing Analytics Tools...")
    
    # 1. Whale Activity (Dune/HL)
    print("  > [Dune] get_whale_activity('BTC')")
    try:
        res = await analytics.get_whale_activity("BTC", min_size_usd=100000)
        print(f"    Result: {str(res)[:150]}...")
    except Exception as e:
        print(f"    Error: {e}")

async def _exercise_analysis_tools():
    """Test Analysis Tools"""
    print("\n[TEST] Testing Analysis Tools...")
    
    # 1. Patterns
    print("  > get_patterns('BTC')")
    try:
        res = await analysis.get_patterns("BTC")
        print(f"    Result: {res}")
    except Exception as e:
        print(f"    Error: {e}")
    
async def _exercise_web_tools():
    """Test Web Tools"""
    print("\n[TEST] Testing Web Tools...")
    
    # 1. News
    print("  > search_news('Crypto regulatory')")
    try:
        res = await web.search_news("Crypto regulatory")
        print(f"    Result: {res}")
    except Exception as e:
        print(f"    Error: {e}")

async def _exercise_memory_tools():
    """Test Memory Tools (mem0)"""
    print("\n[TEST] Testing Memory Tools...")
    
    # 1. Add Memory
    print("  > add_memory('test_user', 'User likes Bitcoin')")
    try:
        res = await memory.add_memory("test_user_01", "User is bullish on BTC")
        print(f"    Result: {res}")
    except Exception as e:
        print(f"    Error: {e}")

    # 2. Search Memory
    print("  > search_memory('test_user', 'bullish')")
    try:
        res = await memory.search_memory("test_user_01", "bullish")
        print(f"    Result: {res}")
    except Exception as e:
        print(f"    Error: {e}")

async def _exercise_knowledge_tools():
    """Test Knowledge Tools (Mock)"""
    print("\n[TEST] Testing Knowledge Tools...")
    
    try:
        res = await knowledge.search_knowledge_base("bull flag")
        print(f"    Result: {res}")
    except Exception as e:
        print(f"    Error: {e}")

def test_market_tools():
    asyncio.run(_exercise_market_tools())


def test_analytics_tools():
    asyncio.run(_exercise_analytics_tools())


def test_analysis_tools():
    asyncio.run(_exercise_analysis_tools())


def test_web_tools():
    asyncio.run(_exercise_web_tools())


def test_memory_tools():
    asyncio.run(_exercise_memory_tools())


def test_knowledge_tools():
    asyncio.run(_exercise_knowledge_tools())
