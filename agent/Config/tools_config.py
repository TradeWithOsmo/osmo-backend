"""
Tools Configuration
"""
import os

DATA_SOURCES = {
    "connectors": os.getenv("CONNECTORS_API_URL", "http://localhost:8000/api/connectors"),
    "analysis": os.getenv("ANALYSIS_API_URL", "http://localhost:8000/api/analysis"),
    "mem0": os.getenv("MEM0_API_URL", "http://localhost:8888"),
    "qdrant": os.getenv("QDRANT_API_URL", "http://localhost:6333")
}
