"""
Config compatibility layer
"""

import sys
from pathlib import Path

# Add src/config to path
src_config = Path(__file__).parent.parent / "src" / "config"
if str(src_config) not in sys.path:
    sys.path.insert(0, str(src_config))

try:
    from tools_config import DATA_SOURCES
except ImportError:
    DATA_SOURCES = {}

__all__ = ["DATA_SOURCES"]
