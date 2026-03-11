"""Runtime utilities for agent request hot-path."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException


def billing_timeout_seconds(
    tool_states: Optional[Dict[str, Any]],
    default_timeout_seconds: float,
) -> float:
    raw = (
        (tool_states or {}).get("billing_timeout_sec")
        if isinstance(tool_states, dict)
        else None
    )
    if raw is None:
        raw = default_timeout_seconds
    try:
        value = float(raw)
    except Exception:
        value = float(default_timeout_seconds)
    return max(1.0, min(value, 120.0))


async def bill_usage_with_timeout(
    ai_billing_service: Any,
    *,
    user_address: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    model_info: Dict[str, Any],
    tool_states: Optional[Dict[str, Any]],
    default_timeout_seconds: float,
) -> Dict[str, Any]:
    timeout_sec = billing_timeout_seconds(tool_states, default_timeout_seconds)
    try:
        return await asyncio.wait_for(
            ai_billing_service.bill_usage(
                user_address=user_address,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model_info=model_info,
            ),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"AI billing timeout after {int(timeout_sec)}s",
        ) from exc


async def persist_ai_output(
    *,
    chat_service: Any,
    usage_service: Any,
    user_address: str,
    auth_user_id: str,
    session_id: str,
    model_id: str,
    content: str,
    input_tokens: int,
    output_tokens: int,
    total_cost: float,
    duration_ms: int = 0,
) -> None:
    await asyncio.gather(
        chat_service.save_message(
            user_address=auth_user_id,
            session_id=session_id,
            role="assistant",
            content=content,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=total_cost,
        ),
        usage_service.log_usage(
            user_address=user_address,
            model=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=total_cost,
            duration_ms=duration_ms,
            session_id=session_id,
        ),
    )
