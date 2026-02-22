from typing import Literal, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration with environment variable support"""

    # Environment
    ENV: str = "development"

    # Network Mode
    NETWORK_MODE: Literal["testnet", "mainnet"] = "testnet"
    NETWORK_NAME: str = "arbitrum_sepolia"

    # Security
    JWT_SECRET: Optional[str] = None
    JWT_EXPIRY_HOURS: int = 1
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:5174,http://localhost:8000"
    RATE_LIMIT_PER_MINUTE: int = 300
    PRIVY_APP_ID: Optional[str] = None
    PRIVY_VERIFICATION_KEY: Optional[str] = None

    # Database
    SAVE_TO_DB: bool = False
    WS_IN_MEMORY_ONLY: bool = True
    DATABASE_URL: str = "postgresql://osmo_user:osmo_password@localhost:5432/osmo_db"
    DB_RETENTION_DAYS: int = 7
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # Hyperliquid
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_RPC_URL: Optional[str] = None
    HYPERLIQUID_TESTNET: bool = False
    HYPERLIQUID_RATE_LIMIT: int = 1200

    # Ostium
    OSTIUM_API_URL: str = "https://metadata-backend.ostium.io"
    OSTIUM_RPC_URL: Optional[str] = None
    OSTIUM_TESTNET: bool = False
    OSTIUM_POLL_INTERVAL: int = 2
    OSMO_BUILDER_ADDRESS: Optional[str] = None
    OSMO_BUILDER_FEE_BPS: int = 50

    # Web3 & Smart Contracts
    ARBITRUM_RPC_URL: str = "https://lb.drpc.live/arbitrum-sepolia/Ap-mSigiUE5YpeoVD1OiMP2Wh_Av-QMR8JYggtEkfQq9"
    ARBITRUM_BACKUP_RPC_URL: str = "https://sepolia-rollup.arbitrum.io/rpc"
    CHAIN_ID: int = 421614
    BLOCK_EXPLORER_URL: str = "https://sepolia.arbiscan.io"

    # Faucet (Testnet Only)
    FAUCET_ENABLED: bool = True
    FAUCET_AUTO_CLAIM: bool = True
    FAUCET_ADDRESS: Optional[str] = None

    # Contract Addresses (Network-specific)
    OSMO_CORE_ADDRESS: Optional[str] = None
    TRADING_VAULT_ADDRESS: Optional[str] = None
    AI_VAULT_ADDRESS: Optional[str] = None
    ORDER_ROUTER_ADDRESS: Optional[str] = None
    POSITION_MANAGER_ADDRESS: Optional[str] = None
    SESSION_KEY_MANAGER_ADDRESS: Optional[str] = None
    PRICE_FEED_ADDRESS: Optional[str] = None
    SYMBOL_REGISTRY_ADDRESS: Optional[str] = None
    RISK_MANAGER_ADDRESS: Optional[str] = None
    OSTIUM_ADAPTER_ADDRESS: Optional[str] = None
    FEE_MANAGER_ADDRESS: Optional[str] = None
    USDC_ADDRESS: Optional[str] = None

    # Web3 Settings
    WEB3_PROVIDER_TIMEOUT: int = 30
    WEB3_MAX_RETRIES: int = 3
    GAS_PRICE_MULTIPLIER: float = 1.2

    # Treasury for automated operations
    TREASURY_PRIVATE_KEY: Optional[str] = None

    # Backend Instance
    BACKEND_INSTANCE_ID: str = "testnet"
    BACKEND_PORT: int = 8001

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
    OPENROUTER_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GROQ_SECONDARY_API_KEY: Optional[str] = None
    GROQ_TERTIARY_API_KEY: Optional[str] = None
    GROQ_QUATERNARY_API_KEY: Optional[str] = None
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_SECONDARY_API_KEY: Optional[str] = None
    NIM_API_KEY: Optional[str] = None
    NVIDIA_TOP_P: float = 1.0
    NVIDIA_MAX_COMPLETION_TOKENS: int = 16384
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "http://langfuse-web:3000"
    LANGFUSE_ENV: str = "development"
    LANGFUSE_RELEASE: Optional[str] = None
    LANGFUSE_LLM_PROVIDER: str = "openrouter"
    LANGFUSE_LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LANGFUSE_LLM_CONNECTION: Optional[str] = None
    LANGFUSE_LLM_CONNECTION_TEMPLATE: Optional[str] = None
    AI_MARKUP_PERCENT: float = 5.0
    AI_BILLING_ONCHAIN_ENABLED: bool = True
    AI_BILLING_SIGNER_PRIVATE_KEY: Optional[str] = None
    AI_BILLING_REQUEST_TIMEOUT_SECONDS: int = 20
    AI_BILLING_RECEIPT_TIMEOUT_SECONDS: int = 90
    AI_BILLING_REQUIRE_OPERATOR_ROLE: bool = True
    GROQ_DEFAULT_INPUT_COST_PER_1M: float = 0.0
    GROQ_DEFAULT_OUTPUT_COST_PER_1M: float = 0.0
    GROQ_MODEL_PRICING_USD_PER_1M: str = ""

    # Secondary session history cache (development)
    SECONDARY_HISTORY_ENABLED: bool = True
    SECONDARY_HISTORY_PREWARM: bool = True
    SESSION_HISTORY_DAYS: int = 7
    SECONDARY_CRYPTO_ONLY: bool = True
    SECONDARY_NON_CRYPTO_PROVIDER: str = "yahoo"
    SECONDARY_DISABLE_COMMODITIES: bool = True

    @property
    def is_testnet(self) -> bool:
        return self.NETWORK_MODE == "testnet"

    @property
    def is_mainnet(self) -> bool:
        return self.NETWORK_MODE == "mainnet"

    class Config:
        import os
        from pathlib import Path

        env_file = os.path.join(Path(__file__).parent, ".env")
        case_sensitive = True
        extra = "ignore"


# Global settings instance
settings = Settings()
