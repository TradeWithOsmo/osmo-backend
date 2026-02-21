"""
Models Config - Compatibility wrapper
Backward compatibility for backend main
"""

import importlib
import sys
from pathlib import Path

# Add agent src to Python path
agent_src = Path(__file__).parent.parent / "src"
if str(agent_src) not in sys.path:
    sys.path.insert(0, str(agent_src))

_import_errors = []
_models_module = None

for module_name in (
    # Preferred import path to avoid collisions with websocket `config.py`.
    "agent.src.config.models_config",
    "src.config.models_config",
):
    try:
        _models_module = importlib.import_module(module_name)
        break
    except Exception as exc:  # pragma: no cover - compatibility fallback path
        _import_errors.append(f"{module_name}: {exc}")

if _models_module is None:
    details = " | ".join(_import_errors) if _import_errors else "unknown import error"
    raise ImportError(f"Unable to import models config module: {details}")

get_model_config = getattr(_models_module, "get_model_config")
get_available_models = getattr(_models_module, "list_available_models")


__all__ = ["get_available_models", "get_model_config"]
