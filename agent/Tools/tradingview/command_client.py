from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple, List

import httpx

try:
    from agent.Config.tools_config import DATA_SOURCES
except Exception:
    from backend.agent.Config.tools_config import DATA_SOURCES


CONNECTORS_API = DATA_SOURCES.get("connectors", "http://localhost:8000/api/connectors")
TRADINGVIEW_WAIT_FOR_COMPLETION = os.getenv("TRADINGVIEW_WAIT_FOR_COMPLETION", "true").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}
TRADINGVIEW_WAIT_TIMEOUT_SEC = max(0.5, float(os.getenv("TRADINGVIEW_WAIT_TIMEOUT_SEC", "6.0")))
TRADINGVIEW_STRICT_WRITE_VERIFICATION = os.getenv("TRADINGVIEW_STRICT_WRITE_VERIFICATION", "true").strip().lower() not in {
    "0",
    "false",
    "off",
    "no",
}


def _command_query_params() -> Dict[str, Any]:
    return {
        "wait_for_completion": "true" if TRADINGVIEW_WAIT_FOR_COMPLETION else "false",
        "timeout_sec": TRADINGVIEW_WAIT_TIMEOUT_SEC,
    }


def _to_json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_symbol(value: Any) -> str:
    text = _as_text(value).upper().replace("_", "-").replace("/", "-")
    if not text:
        return ""
    if "-" in text:
        base, quote = text.split("-", 1)
        if quote in {"USDT", "USD"}:
            return f"{base}-USD"
        return f"{base}-{quote}"
    if text.endswith("USDT") and len(text) > 4:
        return f"{text[:-4]}-USD"
    if text.endswith("USD") and len(text) > 3:
        return f"{text[:-3]}-USD"
    return text


def _norm_timeframe(value: Any) -> str:
    text = _as_text(value).upper()
    if not text:
        return ""
    mapping = {
        "1M": "1m",
        "3M": "3m",
        "5M": "5m",
        "15M": "15m",
        "30M": "30m",
        "1H": "1H",
        "4H": "4H",
        "1D": "1D",
        "1W": "1W",
    }
    return mapping.get(text, text)


def _extract_state_evidence(command_result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(command_result, dict):
        return {}
    payload = command_result.get("result")
    if not isinstance(payload, dict):
        return {}

    evidence: Dict[str, Any] = dict(payload)
    # Support common frontend naming variants.
    if "applied_symbol" in payload and "symbol" not in evidence:
        evidence["symbol"] = payload.get("applied_symbol")
    if "applied_timeframe" in payload and "timeframe" not in evidence:
        evidence["timeframe"] = payload.get("applied_timeframe")
    if "applied_indicator" in payload and "indicator" not in evidence:
        evidence["indicator"] = payload.get("applied_indicator")
    if "state" in payload and isinstance(payload.get("state"), dict):
        nested = payload.get("state") or {}
        for key, value in nested.items():
            evidence.setdefault(key, value)
    return evidence


def _compare_state(expected_state: Dict[str, Any], state_evidence: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    if not expected_state:
        return True, [], []
    missing: List[str] = []
    mismatch: List[str] = []
    for key, expected_value in expected_state.items():
        if key not in state_evidence:
            missing.append(key)
            continue
        actual = state_evidence.get(key)
        if key == "symbol":
            if _norm_symbol(actual) != _norm_symbol(expected_value):
                mismatch.append(f"{key}: expected={_norm_symbol(expected_value)} actual={_norm_symbol(actual)}")
        elif key == "timeframe":
            if _norm_timeframe(actual) != _norm_timeframe(expected_value):
                mismatch.append(f"{key}: expected={_norm_timeframe(expected_value)} actual={_norm_timeframe(actual)}")
        else:
            if _as_text(actual).lower() != _as_text(expected_value).lower():
                mismatch.append(f"{key}: expected={_as_text(expected_value)} actual={_as_text(actual)}")
    return len(missing) == 0 and len(mismatch) == 0, missing, mismatch


async def send_tradingview_command(
    *,
    symbol: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    mode: str,
    expected_state: Optional[Dict[str, Any]] = None,
    strict_write_verification: Optional[bool] = None,
) -> Dict[str, Any]:
    url = f"{CONNECTORS_API}/tradingview/commands"
    request_payload = {
        "symbol": symbol,
        "action": action,
        "params": params or {},
    }

    strict = TRADINGVIEW_STRICT_WRITE_VERIFICATION if strict_write_verification is None else bool(strict_write_verification)
    expected = dict(expected_state or {})

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=request_payload, params=_command_query_params())
        except Exception as exc:
            return {
                "status": "error",
                "transport": "tradingview_command",
                "mode": mode,
                "symbol": symbol,
                "action": action,
                "expected_state": expected,
                "state_evidence": {},
                "state_verified": False,
                "error": f"Failed to send command: {exc}",
            }

    body = _to_json_or_text(resp)
    if resp.status_code >= 400:
        return {
            "status": "error",
            "transport": "tradingview_command",
            "mode": mode,
            "symbol": symbol,
            "action": action,
            "expected_state": expected,
            "state_evidence": {},
            "state_verified": False,
            "error": f"TradingView command HTTP {resp.status_code}",
            "http_status": resp.status_code,
            "raw": body,
        }

    envelope = body if isinstance(body, dict) else {"raw": body}
    status = _as_text(envelope.get("status")).lower() or "unknown"
    command = envelope.get("command") if isinstance(envelope.get("command"), dict) else {}
    command_result = envelope.get("result") if isinstance(envelope.get("result"), dict) else {}
    command_id = _as_text(command.get("command_id"))
    command_result_status = _as_text(command_result.get("status")).lower()
    state_evidence = _extract_state_evidence(command_result)
    state_ok, state_missing, state_mismatch = _compare_state(expected, state_evidence)

    verification = {
        "strict": bool(strict),
        "command_status": status,
        "command_result_status": command_result_status,
        "state_ok": state_ok,
        "state_missing": state_missing,
        "state_mismatch": state_mismatch,
    }

    is_done = status in {"completed", "success", "ok", "done"}
    is_result_ok = command_result_status in {"success", "ok", "done", "completed"} or command_result_status == ""
    is_verified = is_done and is_result_ok and state_ok

    # Strict mode hard-fails write commands with insufficient execution evidence.
    error: Optional[str] = None
    if mode == "write" and strict:
        if not is_done:
            error = f"Write command not completed (status={status or 'unknown'})"
        elif command_result_status and not is_result_ok:
            error = f"Write command result failed (result_status={command_result_status})"
        elif expected and not state_ok:
            if state_missing:
                error = f"Write state verification missing fields: {', '.join(state_missing)}"
            else:
                error = f"Write state verification mismatch: {'; '.join(state_mismatch)}"

    result_payload = {
        "status": "completed" if is_done else status,
        "transport": "tradingview_command",
        "mode": mode,
        "symbol": symbol,
        "action": action,
        "command_id": command_id or None,
        "command": command,
        "command_result": command_result,
        "expected_state": expected,
        "state_evidence": state_evidence,
        "state_verified": bool(is_verified),
        "verification": verification,
    }
    if error:
        result_payload["error"] = error
    return result_payload
