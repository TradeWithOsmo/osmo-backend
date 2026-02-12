"""
Tools Configuration
"""
import os

DATA_SOURCES = {
    "connectors": os.getenv("CONNECTORS_API_URL", "http://localhost:8000/api/connectors"),
    # Analysis route is served by connectors router under /api/connectors/analysis/*
    "analysis": os.getenv("ANALYSIS_API_URL", "http://localhost:8000/api/connectors/analysis"),
    "mem0": os.getenv("MEM0_API_URL", "http://localhost:8888"),
    "qdrant": os.getenv("QDRANT_API_URL", "http://localhost:6333")
}

# setup_trade decision field aliases:
# - GP maps to validation
# - GL maps to invalidation
TRADE_DECISION_FIELD_ALIASES = {
    "validation": ("gp", "validation"),
    "invalidation": ("gl", "invalidation"),
    "targets": ("tp", "tp2", "tp3"),
    "risk_controls": ("sl", "trailing_sl", "be", "liq"),
}

# Trigger comparators used when converting GP/GL touches into decision labels.
TRADE_DECISION_COMPARATORS = {
    "long": {"validation": ">=", "invalidation": "<="},
    "short": {"validation": "<=", "invalidation": ">="},
}
