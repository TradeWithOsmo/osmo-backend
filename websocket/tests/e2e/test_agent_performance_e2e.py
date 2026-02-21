import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import HTTPException

WS_ROOT = Path(__file__).resolve().parents[2]
if str(WS_ROOT) not in sys.path:
    sys.path.insert(0, str(WS_ROOT))

from services.agent_runtime_utils import bill_usage_with_timeout, persist_ai_output
from services.openrouter_service import OpenRouterService


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_models_cache_prevents_concurrent_stampede() -> None:
    service = OpenRouterService()
    service.api_key = "test-key"
    service._models_cache = None
    service._last_fetch = None

    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "anthropic/claude-3.5-sonnet",
                        "name": "Claude 3.5 Sonnet",
                        "context_length": 200000,
                        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    }
                ]
            },
        )
    )

    results = await asyncio.gather(*[service.get_models() for _ in range(8)])

    assert route.call_count == 1
    assert all(isinstance(items, list) for items in results)
    assert all(
        any(m.get("id") == "anthropic/claude-3.5-sonnet" for m in items)
        for items in results
    )


@pytest.mark.asyncio
async def test_bill_usage_with_timeout_raises_http_504() -> None:
    class SlowBillingService:
        async def bill_usage(self, **kwargs):
            await asyncio.sleep(1.2)
            return {"total_cost_usd": 0.1}

    with pytest.raises(HTTPException) as exc:
        await bill_usage_with_timeout(
            SlowBillingService(),
            user_address="0xabc",
            model_id="anthropic/claude-3.5-sonnet",
            input_tokens=100,
            output_tokens=50,
            model_info={"input_cost": 1.0, "output_cost": 1.0},
            tool_states={"billing_timeout_sec": 1},
            default_timeout_seconds=1,
        )

    assert exc.value.status_code == 504


@pytest.mark.asyncio
async def test_persist_ai_output_runs_side_effects_in_parallel() -> None:
    class ChatServiceStub:
        async def save_message(self, **kwargs):
            await asyncio.sleep(0.08)

    class UsageServiceStub:
        async def log_usage(self, **kwargs):
            await asyncio.sleep(0.08)

    start = time.perf_counter()
    await persist_ai_output(
        chat_service=ChatServiceStub(),
        usage_service=UsageServiceStub(),
        user_address="0xabc",
        auth_user_id="0xabc",
        session_id="s-1",
        model_id="anthropic/claude-3.5-sonnet",
        content="hello",
        input_tokens=10,
        output_tokens=20,
        total_cost=0.001,
    )
    elapsed = time.perf_counter() - start

    # Sequential execution would be ~0.16s; parallel should stay well under that.
    assert elapsed < 0.14
