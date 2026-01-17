import sys
import os
import unittest
import pandas as pd

# Add backend to path (which is /app inside container)
sys.path.append("/app")

# Also need to make sure 'analysis' is importable.
# The structure in container:
# /app (contains api_routes.py via mount? No, api_routes is in /app/connectors I think)
# Let's check structure.
# /app is d:\WorkingSpace\backend\websocket
# /app/analysis is d:\WorkingSpace\backend\analysis

from analysis.engine import TechnicalAnalysisEngine

class TestTechnicalAnalysisEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TechnicalAnalysisEngine()
        
    def create_mock_candles(self, length=20, pattern="none"):
        """Create simpler mock candles"""
        data = []
        base_price = 40000
        
        for i in range(length):
            candle = {
                "timestamp": 1000 + i * 60,
                "open": base_price + i*10,
                "high": base_price + i*10 + 20,
                "low": base_price + i*10 - 20,
                "close": base_price + i*10 + 5,
                "volume": 100
            }
            data.append(candle)
            
        # Inject Patterns at the end
        if pattern == "doji":
            # Very small body
            data[-1]['open'] = 42000
            data[-1]['close'] = 42001
            data[-1]['high'] = 42050
            data[-1]['low'] = 41950
            
        elif pattern == "bullish_engulfing":
            # Prev: Red
            data[-2]['open'] = 42000
            data[-2]['close'] = 41900
            # Curr: Green & Engulfs
            data[-1]['open'] = 41850
            data[-1]['close'] = 42050
            
        return data

    def test_indicators_rsi(self):
        """Test RSI calculation"""
        data = self.create_mock_candles(length=50) # Need enough data for RSI 14
        result = self.engine.analyze_ticker("BTC", "1D", data)
        
        self.assertIsNotNone(result['indicators']['RSI_14'])
        self.assertTrue(0 <= result['indicators']['RSI_14'] <= 100)
        print(f"RSI Calculated: {result['indicators']['RSI_14']}")

    def test_pattern_doji(self):
        """Test Doji detection"""
        data = self.create_mock_candles(length=20, pattern="doji")
        result = self.engine.analyze_ticker("BTC", "1D", data)
        self.assertIn("Doji", result['patterns'])
        print("Doji Detected")

    def test_pattern_bullish_engulfing(self):
        """Test Bullish Engulfing detection"""
        data = self.create_mock_candles(length=20, pattern="bullish_engulfing")
        result = self.engine.analyze_ticker("BTC", "1D", data)
        self.assertIn("Bullish Engulfing", result['patterns'])
        print("Bullish Engulfing Detected")

if __name__ == '__main__':
    unittest.main()
