import os
from typing import List, Optional


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with optional default."""
    value = os.getenv(key, default)
    return value.strip() if value else default


def get_env_list(key: str, separator: str = ",") -> List[str]:
    """Get comma-separated environment variable as list."""
    value = get_env(key, "")
    if not value:
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]


def require_env(key: str) -> str:
    """Get required environment variable or raise error."""
    value = get_env(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


class APIConfig:
    """API configuration from environment variables."""

    # OpenRouter
    OPENROUTER_API_KEY = require_env("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL = get_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # App
    APP_NAME = get_env("APP_NAME", "Osmo Agent")
    APP_URL = get_env("APP_URL", "https://tradewithosmo.com")

    # Agent
    DEFAULT_MODEL = get_env("DEFAULT_MODEL", "anthropic/claude-3.5-sonnet")
    DEFAULT_TEMPERATURE = float(get_env("DEFAULT_TEMPERATURE", "0.7"))
    MAX_ITERATIONS = int(get_env("MAX_ITERATIONS", "10"))
    LOG_LEVEL = get_env("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls) -> bool:
        """Validate that all required config is set."""
        try:
            _ = cls.OPENROUTER_API_KEY
            return True
        except ValueError:
            return False
