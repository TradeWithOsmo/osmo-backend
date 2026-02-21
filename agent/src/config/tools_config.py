"""
Tools Configuration
"""

import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _running_in_container() -> bool:
    return os.path.exists("/.dockerenv") or bool(os.getenv("KUBERNETES_SERVICE_HOST"))


DOCKER_MODE = _as_bool(os.getenv("DOCKER_MODE"), default=_running_in_container())

_DOCKER_GATEWAY_HOST = str(
    os.getenv("DOCKER_GATEWAY_HOST") or "host.docker.internal"
).strip()
_DEFAULT_CONNECTORS_HOST = str(
    os.getenv("CONNECTORS_HOST")
    or (_DOCKER_GATEWAY_HOST if DOCKER_MODE else "localhost")
).strip()
_DEFAULT_MEM0_HOST = str(
    os.getenv("MEM0_HOST")
    or (_DOCKER_GATEWAY_HOST if DOCKER_MODE else "localhost")
).strip()

DEFAULT_CONNECTORS = f"http://{_DEFAULT_CONNECTORS_HOST}:8000/api/connectors"
DEFAULT_MEM0 = f"http://{_DEFAULT_MEM0_HOST}:8888"

CONNECTORS_API = str(os.getenv("CONNECTORS_API_URL") or DEFAULT_CONNECTORS).rstrip("/")
ANALYSIS_API = str(os.getenv("ANALYSIS_API_URL") or f"{CONNECTORS_API}/analysis").rstrip("/")
MEM0_API = str(os.getenv("MEM0_API_URL") or DEFAULT_MEM0).rstrip("/")

DATA_SOURCES = {
    "hyperliquid": {
        "enabled": True,
        "base_url": "https://api.hyperliquid.xyz",
        "testnet": False,
    },
    "tradingview": {
        "enabled": True,
        "connection": "websocket",
    },
    "dune": {
        "enabled": False,
    },
    "google_search": {
        "enabled": False,
    },
    # Connector URLs used by agent tools
    "connectors": CONNECTORS_API,
    "analysis": ANALYSIS_API,
    "mem0": MEM0_API,
}

__all__ = ["DATA_SOURCES"]
