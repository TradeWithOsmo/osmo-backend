from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()

class MarketData(BaseModel):
    symbol: str
    price: float
    change24h: float
    change24hPercent: float
    volume24h: float
    high24h: float
    low24h: float
    maxLeverage: int
    category: str

@router.get("/")
async def get_markets():
    # Mock data for now to support frontend
    # In reality, this should come from Hyperliquid/Ostium clients or DB
    return [
        {
            "symbol": "BTC-USD",
            "price": 65000.0,
            "change24h": 1200.0,
            "change24hPercent": 1.8,
            "volume24h": 500000000,
            "high24h": 66000.0,
            "low24h": 64000.0,
            "maxLeverage": 50,
            "category": "crypto"
        },
        {
            "symbol": "ETH-USD",
            "price": 3500.0,
            "change24h": -50.0,
            "change24hPercent": -1.4,
            "volume24h": 200000000,
            "high24h": 3600.0,
            "low24h": 3450.0,
            "maxLeverage": 50,
            "category": "crypto"
        },
        {
            "symbol": "SOL-USD",
            "price": 145.0,
            "change24h": 5.0,
            "change24hPercent": 3.5,
            "volume24h": 100000000,
            "high24h": 150.0,
            "low24h": 140.0,
            "maxLeverage": 50,
            "category": "crypto"
        },
        {
            "symbol": "ARB-USD",
            "price": 1.2,
            "change24h": 0.05,
            "change24hPercent": 4.2,
            "volume24h": 50000000,
            "high24h": 1.25,
            "low24h": 1.15,
            "maxLeverage": 50,
            "category": "crypto"
        }
    ]
