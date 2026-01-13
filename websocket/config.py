from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application configuration with environment variable support"""
    
    # Environment
    ENV: str = "development"
    
    # Security
    JWT_SECRET: Optional[str] = None
    JWT_EXPIRY_HOURS: int = 1
    CORS_ORIGINS: str = "*"
    PRIVY_APP_ID: Optional[str] = None
    PRIVY_VERIFICATION_KEY: Optional[str] = None
    
    # Database
    SAVE_TO_DB: bool = False
    DATABASE_URL: str = "postgresql://osmo_user:osmo_password@localhost:5432/osmo_db"
    DB_RETENTION_DAYS: int = 7
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    
    # Hyperliquid
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_RATE_LIMIT: int = 1200
    
    # Ostium
    OSTIUM_API_URL: str = "https://metadata-backend.ostium.io"
    OSTIUM_POLL_INTERVAL: int = 2
    OSMO_BUILDER_ADDRESS: Optional[str] = None
    OSMO_BUILDER_FEE_BPS: int = 50
    
    # Bridge Monitoring
    ARBITRUM_RPC_URL: str = "https://arb1.arbitrum.io/rpc"
    BRIDGE_CONTRACT_ADDRESS: Optional[str] = None
    BRIDGE_POLL_INTERVAL: int = 15
    
    # Performance & Scalability
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SENTINEL_ENABLED: bool = False
    REDIS_SENTINEL_HOSTS: str = ""
    REDIS_USE_STREAMS: bool = True
    REDIS_STREAM_MAX_LEN: int = 10000
    WS_MAX_CONNECTIONS: int = 1000
    WS_MESSAGE_QUEUE_SIZE: int = 100
    WS_QUEUE_OVERFLOW_STRATEGY: str = "drop_oldest"
    WS_RECONNECT_POLICY: str = "auto"
    WS_MAX_MESSAGE_SIZE_KB: int = 256
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True
    METRICS_PORT: int = 9090
    
    # AI Agent Integration
    AI_AGENT_API_URL: str = "http://localhost:8001"
    AI_WEBHOOK_SECRET: Optional[str] = None
    AI_RATE_LIMIT: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
