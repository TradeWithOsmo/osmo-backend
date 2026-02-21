import json
import os
from typing import Any, Dict, List

import httpx
import pytest


def _first_env(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name, "")).strip()
        if value:
            return value
    return ""


def _read_sse_events(raw_text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    chunks = raw_text.replace("\r\n", "\n").split("\n\n")
    for chunk in chunks:
        lines = [line for line in chunk.split("\n") if line.startswith("data:")]
        if not lines:
            continue
        payload = "\n".join(line[5:].lstrip() for line in lines).strip()
        if not payload:
            continue
        try:
            events.append(json.loads(payload))
        except Exception:
            continue
    return events


@pytest.mark.asyncio
async def test_live_agent_chat_stream_tool_call_end_to_end() -> None:
    """
    Live E2E:
    - Hits /api/agent/chat/stream
    - Verifies SSE flow ends with done
    - Verifies runtime includes tool orchestration with at least one tool call

    Required env:
    - LIVE_E2E_BACKEND_URL (e.g. http://localhost:8000)
    - LIVE_E2E_TOKEN
    - LIVE_E2E_WALLET (0x...)
    Optional:
    - LIVE_E2E_MODEL_ID
    """

    base_url = _first_env("LIVE_E2E_BACKEND_URL", "TOOLS_BENCH_BASE_URL")
    token = _first_env("LIVE_E2E_TOKEN", "TOOLS_BENCH_TOKEN")
    wallet = _first_env("LIVE_E2E_WALLET", "TOOLS_BENCH_WALLET")
    model_id = _first_env("LIVE_E2E_MODEL_ID") or "openrouter/openai/gpt-4o-mini"

    if not base_url or not token or not wallet:
        pytest.skip(
            "Missing LIVE_E2E_BACKEND_URL/LIVE_E2E_TOKEN/LIVE_E2E_WALLET env for live stream e2e."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Wallet-Address": wallet,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model_id": model_id,
        "message": (
            "Analyze BTC-USD timeframe 1H. Wajib gunakan tools harga + technical dulu, "
            "lalu jawab ringkas 2 kalimat."
        ),
        "history": [],
        "tool_states": {
            "strict_react": True,
            "execution": False,
            "write": False,
            "memory_enabled": False,
            "web_observation_enabled": False,
            "max_tool_actions": 3,
            "market_symbol": "BTC-USD",
            "market_timeframe": "1H",
            "policy_mode": "advice_only",
        },
    }

    url = f"{base_url}/api/agent/chat/stream"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        assert response.status_code == 200, response.text[:1000]
        events = _read_sse_events(response.text)

    assert events, "No SSE events parsed from stream response."
    event_types = [str(e.get("type", "")) for e in events]
    assert "done" in event_types, f"Done event missing. Types={event_types}"
    assert "error" not in event_types, f"Error event present: {events[-3:]}"

    runtime_events = [e for e in events if e.get("type") == "runtime"]
    assert runtime_events, "Runtime event missing; tool orchestration not visible."

    runtime = runtime_events[-1].get("runtime", {}) or {}
    assert runtime.get("engine") in {
        "openrouter_http_tools",
        "langchain_openrouter",
    }, runtime

    # Strong verification for end-to-end tool-call flow.
    tool_calls_count = int(runtime.get("tool_calls_count") or 0)
    assert tool_calls_count >= 1, runtime
