from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, Index, Boolean, Date, Text
from sqlalchemy.sql import func
from datetime import datetime
from .connection import Base

class ArenaPick(Base):
    __tablename__ = "arena_picks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    side = Column(String, nullable=False) # 'human' or 'ai'
    wager = Column(Float, default=0.0)
    picked_at = Column(DateTime, default=datetime.utcnow)
    lock_until = Column(DateTime, nullable=False)
    
    # Contract integration metadata
    tx_hash = Column(String, nullable=True)
    status = Column(String, default='confirmed') # 'pending', 'confirmed', 'failed'

    __table_args__ = (
        Index('idx_arena_user_side', 'user_address', 'side'),
    )

class ArenaReward(Base):
    __tablename__ = "arena_rewards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    amount = Column(Float, nullable=False)
    is_claimed = Column(Boolean, default=False)
    claimed_at = Column(DateTime, nullable=True)
    
    # Tracking event/window
    window_id = Column(Integer, index=True) # e.g. 1 for first week

class ArenaLeaderboard(Base):
    __tablename__ = "arena_leaderboard"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    side = Column(String, nullable=False)
    pnl = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    volume = Column(Float, default=0.0)
    rank = Column(Integer, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_arena_lb_side_rank', 'side', 'rank'),
    )
