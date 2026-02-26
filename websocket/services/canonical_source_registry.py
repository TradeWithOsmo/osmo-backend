"""
Canonical Source Registry
=========================
Determines which exchange connector is the authoritative (canonical)
price/chart source for each symbol.

NO hardcoded mappings here.
Source of truth = websocket/contracts/config/symbol_registry.json
(with fallback to legacy contracts paths when present)

Runtime flow:
1. On startup: load from symbol_registry.json  → build in-memory map
2. On cache miss: connector autodiscovery (ask each connector if it has symbol)
3. Redis overrides: admin can change canonical source live without redeploy
4. Heuristic last-resort: pattern-based guess (3-letter alpha → hyperliquid, etc.)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Path to the shared config (resolved at import time)
_CONFIG_PATH = (
    os.environ.get("SYMBOL_REGISTRY_PATH")
    or next(
        (p for p in [
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../contracts/config/symbol_registry.json")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../contracts/config/symbol_registry.json")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../../contracts/config/symbol_registry.json")),
            "/app/contracts/config/symbol_registry.json",
        ] if os.path.exists(p)),
        "/app/contracts/config/symbol_registry.json"
    )
)

# EXCHANGE → connector name (lowercase)
_EXCHANGE_TO_CONNECTOR: Dict[str, str] = {}  # populated from config["exchange_metadata"]

# symbol_base (uppercase) → connector_name : populated from config
_canonical_map: Dict[str, str] = {}

# symbol_base (uppercase) → category : populated from config
_category_map: Dict[str, str] = {}

# symbol_base (uppercase) → sub_category : populated from config
_subcategory_map: Dict[str, str] = {}

# symbol_base (uppercase) → full registry entry : populated from config
_metadata_map: Dict[str, Dict] = {}

# Redis key prefix for live overrides
_REDIS_OVERRIDE_PREFIX = "canonical_source:override:"


def _load_from_config() -> None:
    """Parse symbol_registry.json and populate _canonical_map."""
    global _EXCHANGE_TO_CONNECTOR

    if not os.path.exists(_CONFIG_PATH):
        logger.warning(
            f"[CanonicalRegistry] Config not found at {_CONFIG_PATH} — "
            "falling back to heuristic detection only"
        )
        return

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Build exchange → connector map
        for exc, meta in config.get("exchange_metadata", {}).items():
            _EXCHANGE_TO_CONNECTOR[exc.upper()] = meta.get("connector", exc.lower())

        # Build canonical source map: only entries where canonical=true
        for entry in config.get("symbols", []):
            if not entry.get("canonical", False):
                continue
            trading_symbol: str = entry.get("tradingSymbol", "").upper()
            exchange: str = entry.get("exchange", "").upper()
            connector = _EXCHANGE_TO_CONNECTOR.get(exchange, exchange.lower())
            
            # Use chainlink target base to map category (e.g., BTC from BTC-USD)
            chainlink = entry.get("chainlinkSymbol", "").split("-")[0].upper()
            mapping_key = chainlink if chainlink else trading_symbol
            cat_key = chainlink if chainlink else trading_symbol

            if mapping_key and connector:
                _canonical_map[mapping_key] = connector
                _metadata_map[mapping_key] = entry
                
            category: str = entry.get("category", "")
            if category:
                _category_map[cat_key] = category
                # Also fallback to trading symbol if they differ
                if cat_key != mapping_key:
                    _category_map[mapping_key] = category

            sub_category: str = entry.get("subCategory", "")
            if sub_category:
                _subcategory_map[cat_key] = sub_category
                if cat_key != mapping_key:
                    _subcategory_map[mapping_key] = sub_category

        logger.info(
            f"[CanonicalRegistry] Loaded {len(_canonical_map)} canonical mappings "
            f"from {_CONFIG_PATH}"
        )
    except Exception as e:
        logger.error(f"[CanonicalRegistry] Failed to load config: {e}")


# Load on module import
_load_from_config()


# ---------------------------------------------------------------------------
# Heuristic fallback — no hardcoded lists, uses pattern-based rules
# ---------------------------------------------------------------------------

# Known RWA patterns (forex pairs, commodities)
_FOREX_PATTERN = re.compile(r"^[A-Z]{3}(USD|EUR|GBP|JPY|CAD|CHF|AUD|NZD|MXN)$")
_COMMODITY_PATTERN = re.compile(r"^(XAU|XAG|WTI|BRN|NG|GC|SI|HG|CL|OIL|GOLD|SILVER|PLATINUM|PALLADIUM)")
_INDEX_PATTERN = re.compile(r"^(SPX|NDX|DJI|DAX|FTSE|NIK|HSI|VIX)")


def _heuristic_source(symbol_base: str) -> str:
    """
    Guess canonical source from symbol pattern.
    Order: commodity → ostium, forex → ostium, index → ostium,
    else → hyperliquid (most DEX crypto lands here).
    """
    s = symbol_base.upper()
    if _COMMODITY_PATTERN.match(s):
        return "ostium"
    if _FOREX_PATTERN.match(s):
        return "ostium"
    if _INDEX_PATTERN.match(s):
        return "ostium"
    # Short alpha-only ticker → assume crypto on hyperliquid
    if len(s) <= 6 and s.isalpha():
        return "hyperliquid"
    return "hyperliquid"


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class CanonicalSourceRegistry:
    """
    Resolves the canonical price/chart source for any symbol.
    Priority: Redis override > config file > heuristic.
    """

    def __init__(self):
        self._redis = None  # injected at startup if Redis is available

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    def reload_from_config(self) -> None:
        """Hot-reload config without restarting."""
        _canonical_map.clear()
        _category_map.clear()
        _subcategory_map.clear()
        _EXCHANGE_TO_CONNECTOR.clear()
        _load_from_config()

    async def get_canonical_source(self, symbol: str) -> str:
        """
        Return connector name that is canonical for this symbol.
        Checks: Redis override → config file → heuristic.
        """
        base = symbol.upper().split("-")[0]  # "BTC-USD" → "BTC"

        # 1. Redis live override
        if self._redis:
            try:
                override = await self._redis.get(f"{_REDIS_OVERRIDE_PREFIX}{base}")
                if override:
                    logger.debug(f"[CanonicalRegistry] Redis override {base} → {override}")
                    return override
            except Exception:
                pass

        # 2. Config file map
        if base in _canonical_map:
            return _canonical_map[base]

        # 3. Heuristic (no hardcoded lists)
        src = _heuristic_source(base)
        logger.debug(f"[CanonicalRegistry] Heuristic {base} → {src}")
        return src

    def get_canonical_source_sync(self, symbol: str) -> str:
        """
        Sync version (no Redis check). Used in non-async contexts.
        """
        base = symbol.upper().split("-")[0]
        if base in _canonical_map:
            return _canonical_map[base]
        return _heuristic_source(base)

    def is_canonical_source(self, symbol: str, connector_name: str) -> bool:
        """
        Returns True if connector_name is canonical for this symbol.
        Used to gate which sources write to candle cache.
        """
        return self.get_canonical_source_sync(symbol) == connector_name

    def get_category_sync(self, symbol: str) -> str:
        """
        Returns category mapped for this symbol. 
        Falls back to heuristics if missing.
        """
        base = symbol.upper().split("-")[0]
        if base in _category_map:
            return _category_map[base]

        if _COMMODITY_PATTERN.match(base):
            return "Commodities"
        if _FOREX_PATTERN.match(base):
            return "Forex"
        if _INDEX_PATTERN.match(base):
            return "Index"
        return "Crypto"

    def get_subcategory_sync(self, symbol: str) -> str:
        """
        Returns sub-category mapped for this symbol.
        """
        base = symbol.upper().split("-")[0]
        return _subcategory_map.get(base, "ALT")

    async def set_override(self, symbol_base: str, connector_name: str) -> None:
        """Persist a live override to Redis (survives hot-reload, not restarts)."""
        base = symbol_base.upper()
        if self._redis:
            await self._redis.set(f"{_REDIS_OVERRIDE_PREFIX}{base}", connector_name)
        logger.info(f"[CanonicalRegistry] Override set: {base} → {connector_name}")

    async def clear_override(self, symbol_base: str) -> None:
        """Remove Redis override, revert to config/heuristic."""
        base = symbol_base.upper()
        if self._redis:
            await self._redis.delete(f"{_REDIS_OVERRIDE_PREFIX}{base}")
        logger.info(f"[CanonicalRegistry] Override cleared: {base}")

    def get_all_canonical_map(self) -> Dict[str, str]:
        """Return the config-loaded map (does not include Redis overrides)."""
        return dict(_canonical_map)

    def get_symbol_info_sync(self, symbol: str) -> Optional[Dict]:
        """Return the actual registry entry for a canonical base symbol."""
        base = symbol.upper().split("-")[0]
        return _metadata_map.get(base)


# Singleton
canonical_registry = CanonicalSourceRegistry()
