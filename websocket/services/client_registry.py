"""
client_registry.py
==================
Shared registry for exchange API clients (Aster, Vest, Avantis, Orderly, Paradex, Aevo, dYdX).
Ensures we don't recreate clients on every request.
"""
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

_clients: Dict[str, Any] = {}

def get_exchange_client(name: str) -> Optional[Any]:
    """Lazy-initialize and return an exchange client singleton."""
    name = name.lower()
    if name in _clients:
        return _clients[name]
        
    try:
        if name == "avantis":
            from Avantis.api_client import AvantisAPIClient
            _clients[name] = AvantisAPIClient()
        elif name == "aster":
            from Aster.api_client import AsterAPIClient
            _clients[name] = AsterAPIClient()
        elif name == "vest":
            from Vest.api_client import VestAPIClient
            _clients[name] = VestAPIClient()
        elif name == "orderly":
            from Orderly.api_client import OrderlyAPIClient
            _clients[name] = OrderlyAPIClient()
        elif name == "paradex":
            from Paradex.api_client import ParadexAPIClient
            _clients[name] = ParadexAPIClient()
        elif name == "aevo":
            from Aevo.api_client import AevoAPIClient
            _clients[name] = AevoAPIClient()
        elif name == "dydx":
            from dYdX.api_client import DydxAPIClient
            _clients[name] = DydxAPIClient()
        return _clients.get(name)
    except Exception as e:
        logger.error(f"[ClientRegistry] Failed to init {name}: {e}")
        return None

async def close_all_clients():
    """Cleanup all active clients during shutdown."""
    for name, client in _clients.items():
        try:
            if hasattr(client, "close"):
                await client.close()
            elif hasattr(client, "client") and hasattr(client.client, "aclose"):
                await client.client.aclose()
        except Exception as e:
            logger.debug(f"[ClientRegistry] Error closing {name}: {e}")
    _clients.clear()
