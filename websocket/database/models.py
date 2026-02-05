from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, Index, Boolean, Date, Text
from sqlalchemy.sql import func
from datetime import datetime
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

class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String, index=True, nullable=True) # Optional for now
    symbol = Column(String, index=True, nullable=False)
    source = Column(String, nullable=True) # hyperliquid or ostium

class LedgerAccount(Base):
    """Off-chain Ledger for high-frequency trading balance"""
    __tablename__ = "ledger_accounts"
    
    address = Column(String, primary_key=True)  # Wallet Address
    balance = Column(Float, default=0.0)  # Realized Balance (Deposits + Realized PnL)
    locked_margin = Column(Float, default=0.0)  # Margin locked in open positions
    available_balance = Column(Float, default=0.0)  # balance - locked_margin (Cached for speed)
    
    realized_pnl = Column(Float, default=0.0)  # Total historical PnL
    
    last_updated_block = Column(BigInteger, default=0) # For sync safety with Vault
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(Base):
    """User order records for trading engine"""
    __tablename__ = "orders"
    
    id = Column(String, primary_key=True)  # UUID (KECCAK256 from Contract or Backend)
    user_address = Column(String, index=True, nullable=False)
    exchange = Column(String, nullable=False)  # 'hyperliquid' | 'ostium'
    symbol = Column(String, nullable=False)  # 'BTC-USD', 'EURUSD'
    side = Column(String, nullable=False)  # 'buy' | 'sell'
    order_type = Column(String, nullable=False)  # 'market' | 'limit' | 'stop_market' | 'stop_limit'
    
    # Prices
    price = Column(Float, nullable=True)  # Limit price
    trigger_price = Column(Float, nullable=True)  # Stop/Trigger price
    trigger_condition = Column(String, nullable=True) # 'ABOVE', 'BELOW'

    
    # Advanced Options
    reduce_only = Column(Boolean, default=False)
    post_only = Column(Boolean, default=False)
    time_in_force = Column(String, default='GTC')
    
    # Size & Leverage
    size = Column(Float, nullable=False)  # Contract size
    notional_usd = Column(Float, nullable=False)  # USD value
    leverage = Column(Integer, default=1)
    
    # Execution
    status = Column(String, default='pending')  # 'pending' | 'filled' | 'cancelled' | 'rejected'
    filled_size = Column(Float, default=0)
    avg_fill_price = Column(Float, nullable=True)
    realized_pnl = Column(Float, default=0) # PnL realized by this specific order execution
    
    # Advanced Order Params (Added for Simulation/Limit/Stop)
    stop_price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)
    trigger_condition = Column(String, nullable=True) # 'ABOVE', 'BELOW'
    reduce_only = Column(Boolean, default=False)
    post_only = Column(Boolean, default=False)
    time_in_force = Column(String, default='GTC')
    
    # Exchange identifiers
    exchange_order_id = Column(String, nullable=True)  # ID from Hyperliquid/Ostium
    
    # Agent Integration (NEW)
    is_agent_trade = Column(Boolean, default=False)  # Flag for AI agent orders
    agent_model = Column(String, nullable=True)  # 'gpt-4o', 'claude-3.5-sonnet', etc
    agent_session_id = Column(String, nullable=True)  # Link to agent session
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_user_status', 'user_address', 'status'),
        Index('idx_exchange_order', 'exchange', 'exchange_order_id'),
        Index('idx_agent_model', 'agent_model'),  # NEW: For agent leaderboard queries
    )

class Position(Base):
    """Active trading positions"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    exchange = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    position_id = Column(String, nullable=True, index=True) # On-chain ID (bytes32 hex)
    
    # Position details
    side = Column(String, nullable=False)  # 'long' | 'short'
    size = Column(Float, nullable=False)  # Current position size
    entry_price = Column(Float, nullable=False)
    leverage = Column(Integer, nullable=False)
    
    # P&L tracking
    unrealized_pnl = Column(Float, default=0)
    realized_pnl = Column(Float, default=0)
    
    # Risk management
    liquidation_price = Column(Float, nullable=True)
    margin_used = Column(Float, nullable=False)
    
    # Active orders
    tp = Column(String, nullable=True) # "Take Profit" price/value
    sl = Column(String, nullable=True) # "Stop Loss" price/value
    
    # Status
    status = Column(String, default='OPEN') # 'OPEN', 'CLOSED'
    
    # Timestamps
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, onupdate=datetime.utcnow, nullable=True)
    
    # Composite unique constraint
    __table_args__ = (
        Index('idx_user_symbol', 'user_address', 'symbol', 'exchange'),
    )

class LeaderboardSnapshot(Base):
    """Daily snapshots for trader leaderboard (per user)"""
    __tablename__ = "leaderboard_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    timeframe = Column(String, nullable=False)  # '24h', '7d', '30d', 'all'
    user_address = Column(String, nullable=False, index=True)
    
    # Metrics
    account_value = Column(Float, default=0)
    pnl = Column(Float, default=0)
    roi = Column(Float, default=0)  # Percentage
    volume = Column(Float, default=0)
    trade_count = Column(Integer, default=0)
    win_rate = Column(Float, default=0)  # Percentage
    
    # Agent info (optional - NULL if manual trading)
    agent_model = Column(String, nullable=True)
    
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_snapshot_user', 'snapshot_date', 'timeframe', 'user_address', unique=True),
        Index('idx_snapshot_rank', 'snapshot_date', 'timeframe', 'rank'),
    )

class ModelLeaderboardSnapshot(Base):
    """Daily snapshots for agent leaderboard (global per model)"""
    __tablename__ = "model_leaderboard_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    timeframe = Column(String, nullable=False)  # '24h', '7d', '30d', 'all'
    agent_model = Column(String, nullable=False, index=True)  # 'gpt-4o', 'claude-3.5-sonnet'
    
    # Aggregated Metrics (combined from all users using this model)
    total_users = Column(Integer, default=0)  # How many users use this model
    account_value = Column(Float, default=0)  # Combined total
    pnl = Column(Float, default=0)  # Combined PNL
    roi = Column(Float, default=0)  # Average ROI
    volume = Column(Float, default=0)  # Combined volume
    trade_count = Column(Integer, default=0)
    win_rate = Column(Float, default=0)  # Average Win Rate
    
    rank = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_model_snapshot', 'snapshot_date', 'timeframe', 'agent_model', unique=True),
        Index('idx_model_rank', 'snapshot_date', 'timeframe', 'rank'),
    )


class PortfolioSnapshot(Base):
    """Portfolio value snapshots for chart data"""
    __tablename__ = "portfolio_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    
    # Snapshot Values
    portfolio_value = Column(Float, nullable=False)  # Total portfolio value
    cash_balance = Column(Float, default=0)  # Available cash
    position_value = Column(Float, default=0)  # Value in open positions
    unrealized_pnl = Column(Float, default=0)  # Unrealized P&L
    realized_pnl = Column(Float, default=0)  # Cumulative realized P&L
    
    __table_args__ = (
        Index('idx_portfolio_user_time', 'user_address', 'timestamp'),
    )



class OnchainTransaction(Base):
    """Track on-chain transaction status"""
    __tablename__ = "onchain_transactions"
    
    id = Column(String, primary_key=True) # tx_hash
    user_address = Column(String, nullable=False, index=True)
    session_address = Column(String, nullable=True) # Key used to sign
    
    # Details
    contract_name = Column(String, nullable=False) # 'OrderRouter', 'TradingVault'
    function_name = Column(String, nullable=False) # 'placeOrder', 'deposit'
    params = Column(Text, nullable=True) # JSON args
    
    # Status
    status = Column(String, default='pending') # 'pending', 'confirmed', 'failed'
    block_number = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

class AIUsageLog(Base):
    """Log of individual AI agent requests"""
    __tablename__ = "ai_usage_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True) # Optional link to chat/agent session
    
    model = Column(String, nullable=False) # 'gpt-4o', 'claude-3.5-sonnet'
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_usage_user_time', 'user_address', 'timestamp'),
    )

class DailyUsageSnapshot(Base):
    """Daily aggregation of AI usage for charts"""
    __tablename__ = "daily_usage_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    user_address = Column(String, nullable=False, index=True)
    
    total_cost = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    request_count = Column(Integer, default=0)
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_daily_usage_user', 'date', 'user_address', unique=True),
    )

class SessionKey(Base):
    """Session keys for AI agent trading authorization"""
    __tablename__ = "session_keys"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    session_address = Column(String, nullable=False, unique=True)  # Public address of session key
    encrypted_private_key = Column(Text, nullable=False)  # Encrypted or plain private key (demo mode)
    
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_session_user_active', 'user_address', 'is_active'),
        Index('idx_session_address', 'session_address'),
        {'extend_existing': True}
    )

class FundingHistory(Base):
    """History of Deposits and Withdrawals"""
    __tablename__ = "funding_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_address = Column(String, index=True, nullable=False)
    type = Column(String, nullable=False)  # 'Deposit' | 'Withdraw'
    asset = Column(String, nullable=False) # 'USDC', 'ETH'
    amount = Column(Float, nullable=False)
    tx_hash = Column(String, nullable=False, unique=True)
    status = Column(String, default='Completed') # 'Completed', 'Pending', 'Failed'
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_funding_user_time', 'user_address', 'timestamp'),
    )

