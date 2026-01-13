from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, Index
from sqlalchemy.sql import func
from .connection import Base

class Candle(Base):
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False, index=True) # Milliseconds
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    interval = Column(String, default="1m")
    source = Column(String, default="ostium")
    
    # Composite index for querying candles by symbol and time
    __table_args__ = (
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True, nullable=False)
    price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    side = Column(String, nullable=False) # buy/sell
    timestamp = Column(BigInteger, nullable=False)
    source = Column(String, default="hyperliquid")
