from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Mapping, Sequence, Tuple, Union, get_args, get_origin


class ToolArgumentParseError(Exception):
    def __init__(self, message: str, details: Dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def _unwrap_optional(annotation: Any) -> Tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Cannot coerce '{value}' to bool")


def _coerce_json(value: Any) -> Any:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("{") or raw.startswith("["):
            return json.loads(raw)
    return value


def coerce_value(value: Any, annotation: Any) -> Any:
    if isinstance(annotation, str):
        lower = annotation.strip().lower()
        if lower in {"str", "string"}:
            annotation = str
        elif lower in {"int", "integer"}:
            annotation = int
        elif lower in {"float", "number"}:
            annotation = float
        elif lower in {"bool", "boolean"}:
            annotation = bool
        elif lower in {"dict", "mapping", "object"}:
            annotation = Dict[str, Any]
        elif lower in {"list", "array", "sequence"}:
            annotation = List[Any]

    if annotation in (inspect._empty, Any):
        return value

    annotation, _ = _unwrap_optional(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union:
        last_error: Exception | None = None
        for candidate in args:
            try:
                return coerce_value(value, candidate)
            except Exception as exc:  # pragma: no cover - best effort
                last_error = exc
                continue
        if last_error:
            raise last_error
        return value

    if annotation is bool:
        return _coerce_bool(value)
    if annotation is int:
        if isinstance(value, bool):
            raise ValueError("bool is not a valid int for this parser")
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is str:
        return str(value)

    if origin in (list, List, Sequence):
        data = _coerce_json(value)
        if not isinstance(data, list):
            raise ValueError(f"Expected list, got {type(data).__name__}")
        inner = args[0] if args else Any
        return [coerce_value(item, inner) for item in data]

    if origin in (dict, Dict, Mapping):
        data = _coerce_json(value)
        if not isinstance(data, dict):
            raise ValueError(f"Expected object, got {type(data).__name__}")
        if len(args) >= 2:
            key_t, val_t = args[0], args[1]
            return {coerce_value(k, key_t): coerce_value(v, val_t) for k, v in data.items()}
        return data

    # For unknown annotations/classes, pass-through.
    return value


def parse_tool_arguments(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    signature: inspect.Signature,
    allow_unknown: bool,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    parsed: Dict[str, Any] = {}
    unknown: Dict[str, Any] = {}
    errors: List[Dict[str, Any]] = []
    parameters = signature.parameters

    for key, value in (arguments or {}).items():
        param = parameters.get(key)
        if param is None:
            if allow_unknown:
                parsed[key] = value
            else:
                unknown[key] = value
            continue

        try:
            parsed[key] = coerce_value(value, param.annotation)
        except Exception as exc:
            errors.append({"field": key, "value": value, "reason": str(exc)})

    if errors:
        raise ToolArgumentParseError(
            f"Tool argument parser failed for '{tool_name}'",
            details={"tool": tool_name, "errors": errors},
        )

    return parsed, {"unknown_fields": sorted(unknown.keys())}
