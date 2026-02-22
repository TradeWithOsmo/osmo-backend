"""
Agent API Router
Handles AI Chat interactions and model discovery.
"""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from auth.dependencies import get_current_user
from config import settings
from database.connection import get_db
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.agent_runtime_utils import (
    bill_usage_with_timeout as bill_usage_with_timeout_util,
)
from services.agent_runtime_utils import (
    persist_ai_output as persist_ai_output_util,
)
from services.langfuse_service import langfuse_service
from services.portfolio_service import PortfolioService
from sqlalchemy.orm import Session

from agent.Config.models_config import get_available_models, get_model_config
from agent.Core.agent_brain import AgentBrain

try:
    from agent.Orchestrator.trace_store import runtime_trace_store
except Exception:
    from backend.agent.Orchestrator.trace_store import runtime_trace_store
try:
    from agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator
except Exception:
    from backend.agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator

router = APIRouter(tags=["Agent"])
logger = logging.getLogger(__name__)

_ACTIVE_STREAMS: Dict[tuple[str, str], asyncio.Task] = {}
DEFAULT_CHAT_STREAM_TIMEOUT_SECONDS = 500.0
MAX_CHAT_STREAM_TIMEOUT_SECONDS = 900.0


def _stream_key(user_id: str, session_id: str) -> tuple[str, str]:
    return (str(user_id or "").strip(), str(session_id or "").strip())


def _register_active_stream(
    user_id: str, session_id: str, task: Optional[asyncio.Task]
) -> None:
    if task is None:
        return
    key = _stream_key(user_id, session_id)
    if not key[0] or not key[1]:
        return
    _ACTIVE_STREAMS[key] = task


def _unregister_active_stream(
    user_id: str, session_id: str, task: Optional[asyncio.Task] = None
) -> None:
    key = _stream_key(user_id, session_id)
    existing = _ACTIVE_STREAMS.get(key)
    if existing is None:
        return
    if task is None or existing is task:
        _ACTIVE_STREAMS.pop(key, None)


def _interrupt_active_stream(user_id: str, session_id: str) -> bool:
    key = _stream_key(user_id, session_id)
    task = _ACTIVE_STREAMS.get(key)
    if task is None:
        return False
    if task.done():
        _ACTIVE_STREAMS.pop(key, None)
        return False
    task.cancel()
    return True


def _start_background_task(
    coro: "asyncio.Future[Any] | asyncio.Task[Any] | Any",
) -> None:
    """Schedule a background coroutine and surface uncaught exceptions in logs."""
    task = asyncio.create_task(coro)

    def _on_done(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception as exc:
            logger.warning("Background task failed: %s", exc)

    task.add_done_callback(_on_done)


def _billing_timeout_seconds(tool_states: Optional[Dict[str, Any]]) -> float:
    raw = (
        (tool_states or {}).get("billing_timeout_sec")
        if isinstance(tool_states, dict)
        else None
    )
    if raw is None:
        raw = getattr(settings, "AI_BILLING_REQUEST_TIMEOUT_SECONDS", 20)
    try:
        value = float(raw)
    except Exception:
        value = 20.0
    return max(1.0, min(value, 120.0))


async def _bill_usage_with_timeout(
    ai_billing_service: Any,
    *,
    user_address: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    model_info: Dict[str, Any],
    tool_states: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return await bill_usage_with_timeout_util(
        ai_billing_service,
        user_address=user_address,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_info=model_info,
        tool_states=tool_states,
        default_timeout_seconds=float(
            getattr(settings, "AI_BILLING_REQUEST_TIMEOUT_SECONDS", 20)
        ),
    )


async def _persist_ai_output(
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
) -> None:
    await persist_ai_output_util(
        chat_service=chat_service,
        usage_service=usage_service,
        user_address=user_address,
        auth_user_id=auth_user_id,
        session_id=session_id,
        model_id=model_id,
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
    )


def _log_langfuse_success_async(
    trace_ctx: Dict[str, Any],
    *,
    model_id: str,
    input_text: str,
    output_text: str,
    usage: Dict[str, Any],
    metadata: Dict[str, Any],
) -> None:
    _start_background_task(
        asyncio.to_thread(
            langfuse_service.log_success,
            trace_ctx,
            model_id=model_id,
            input_text=input_text,
            output_text=output_text,
            usage=usage,
            metadata=metadata,
        )
    )


def _log_langfuse_error_async(
    trace_ctx: Dict[str, Any],
    *,
    model_id: Optional[str],
    input_text: str,
    error_message: str,
    metadata: Dict[str, Any],
) -> None:
    _start_background_task(
        asyncio.to_thread(
            langfuse_service.log_error,
            trace_ctx,
            model_id=model_id,
            input_text=input_text,
            error_message=error_message,
            metadata=metadata,
        )
    )


def _model_base_id(model_id: Optional[str]) -> str:
    raw = (model_id or "").strip()
    return raw.split(":", 1)[0] if raw else ""


def _normalize_model_id_for_runtime(model_id: str) -> str:
    """
    Normalize legacy provider prefixes so runtime stays OpenRouter-first.
    """
    raw = str(model_id or "").strip()
    if "/" not in raw:
        return raw[:-5] if raw.lower().endswith(":free") else raw
    prefix, remainder = raw.split("/", 1)
    if prefix.lower() in {"nvidia", "openrouter"} and remainder:
        raw = remainder
    if raw.lower().endswith(":free"):
        raw = raw[:-5]
    return raw


def _looks_like_wallet(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw.startswith("0x") or len(raw) != 42:
        return False
    try:
        int(raw[2:], 16)
        return True
    except Exception:
        return False


def _resolve_wallet_address(user: Dict[str, Any]) -> str:
    wallet = str(user.get("wallet_address") or "").strip()
    subject = str(user.get("sub") or "").strip()
    direct_address = str(user.get("address") or "").strip()
    if _looks_like_wallet(wallet):
        return wallet.lower()
    if _looks_like_wallet(subject):
        return subject.lower()
    if _looks_like_wallet(direct_address):
        return direct_address.lower()
    return ""


def _resolve_auth_user_id(user: Dict[str, Any]) -> str:
    wallet = _resolve_wallet_address(user)
    if _looks_like_wallet(wallet):
        return wallet.lower()
    subject = str(user.get("sub") or "").strip()
    return subject or wallet


def _require_wallet_address(user: Dict[str, Any]) -> str:
    wallet = _resolve_wallet_address(user)
    if not _looks_like_wallet(wallet):
        raise HTTPException(
            status_code=401,
            detail="Wallet address not found in authentication context. Please reconnect wallet.",
        )
    return wallet.lower()


def _billing_failure_message(billing: Dict[str, Any]) -> str:
    onchain = billing.get("onchain") if isinstance(billing, dict) else {}
    if not isinstance(onchain, dict):
        onchain = {}
    reason = str(onchain.get("reason") or "unknown")
    return (
        f"AI Vault charge failed ({reason}). "
        "Chat was not saved and usage was not recorded."
    )


def _require_successful_billing(billing: Dict[str, Any]) -> None:
    total_cost = (
        float(billing.get("total_cost_usd") or 0.0)
        if isinstance(billing, dict)
        else 0.0
    )
    if total_cost <= 0:
        return
    onchain = billing.get("onchain") if isinstance(billing, dict) else {}
    if isinstance(onchain, dict) and bool(onchain.get("charged")):
        return
    raise HTTPException(status_code=402, detail=_billing_failure_message(billing))


def _is_model_enabled(model_id: str, enabled_models: Optional[List[str]]) -> bool:
    if not model_id:
        return False
    enabled = enabled_models or []
    if model_id in enabled:
        return True
    model_base = _model_base_id(model_id)
    if not model_base:
        return False
    enabled_bases = {_model_base_id(m) for m in enabled}
    return model_base in enabled_bases


def _is_plan_mode_enabled(tool_states: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(tool_states, dict):
        return False
    raw = tool_states.get("plan_mode")
    if raw is None:
        return False
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "off", "no"}
    return bool(raw)


def _extract_active_context(tool_states: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(tool_states, dict):
        return {}

    def _clean_text(value: Any, *, limit: int = 800) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        if len(text) > limit:
            return text[: limit - 3] + "..."
        return text

    market_raw = (
        tool_states.get("market_symbol")
        or tool_states.get("market")
        or tool_states.get("market_display")
        or ""
    )
    market_raw = str(market_raw).strip()
    market_symbol = market_raw.replace("/", "-").upper() if market_raw else ""
    market_display = market_raw.replace("-", "/").upper() if market_raw else ""

    raw_tf = tool_states.get("timeframe")
    timeframes: List[str] = []
    if isinstance(raw_tf, str) and raw_tf.strip():
        timeframes = [raw_tf.strip()]
    elif isinstance(raw_tf, list):
        timeframes = [str(item).strip() for item in raw_tf if str(item).strip()]

    primary_tf = timeframes[0] if timeframes else ""
    joined_tf = ",".join(timeframes)

    payload: Dict[str, str] = {}
    if market_symbol:
        payload["market_symbol"] = market_symbol
    if market_display:
        payload["market_display"] = market_display
    if primary_tf:
        payload["timeframe"] = primary_tf
    if joined_tf:
        payload["timeframes"] = joined_tf

    conversation_style = _clean_text(tool_states.get("conversation_style"), limit=64)
    if conversation_style:
        payload["conversation_style"] = conversation_style

    trading_style_profile = _clean_text(
        tool_states.get("trading_style") or tool_states.get("trading_style_profile"),
        limit=64,
    )
    if trading_style_profile and trading_style_profile.lower() not in {
        "off",
        "none",
        "default",
    }:
        payload["trading_style_profile"] = trading_style_profile

    trading_style_prompt = _clean_text(
        tool_states.get("trading_style_prompt"), limit=700
    )
    if trading_style_prompt:
        payload["trading_style_prompt"] = trading_style_prompt

    # Optional balance context for safer execution sizing.
    balance_values = {
        "account_value_usd": tool_states.get("account_value_usd"),
        "free_collateral_usd": tool_states.get("free_collateral_usd")
        if tool_states.get("free_collateral_usd") is not None
        else tool_states.get("trading_balance_usd"),
        "locked_margin_usd": tool_states.get("locked_margin_usd"),
        "position_margin_usd": tool_states.get("position_margin_usd"),
        "max_order_margin_usd": tool_states.get("max_order_margin_usd"),
    }
    for key, raw_value in balance_values.items():
        parsed = _to_finite_number(raw_value)
        if parsed is not None:
            payload[key] = f"{parsed:.2f}"
    return payload


def _trim_history_for_runtime(
    history: Optional[List[Dict[str, str]]],
    *,
    max_messages: int = 30,
    max_chars_per_message: int = 4000,
) -> List[Dict[str, str]]:
    if not isinstance(history, list):
        return []
    trimmed: List[Dict[str, str]] = []
    for item in history[-max_messages:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        if role not in {"system", "assistant", "user"}:
            role = "user"
        content = str(item.get("content") or "")
        if len(content) > max_chars_per_message:
            content = content[:max_chars_per_message]
        if not content.strip():
            continue
        trimmed.append({"role": role, "content": content})
    return trimmed


def _parse_bool_flag(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no"}
    return bool(value)


def _to_finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed:  # NaN
        return None
    if parsed in (float("inf"), float("-inf")):
        return None
    return parsed


async def _inject_runtime_balance_context(
    tool_states: Optional[Dict[str, Any]],
    *,
    user_address: str,
    db: Session,
) -> Dict[str, Any]:
    """
    Enrich runtime tool_states with user balance context so the agent can size orders.
    """
    runtime_tool_states = dict(tool_states or {})
    if not _looks_like_wallet(user_address):
        return runtime_tool_states

    try:
        portfolio_service = PortfolioService(db)
        metrics = await asyncio.wait_for(
            portfolio_service.calculate_portfolio_value(user_address), timeout=1.5
        )
        account_value = float(metrics.get("portfolio_value") or 0.0)
        free_collateral = float(metrics.get("cash_balance") or 0.0)
        locked_margin = float(metrics.get("locked_margin") or 0.0)
        position_margin = float(metrics.get("position_value") or 0.0)

        runtime_tool_states["account_value_usd"] = round(account_value, 2)
        runtime_tool_states["free_collateral_usd"] = round(free_collateral, 2)
        runtime_tool_states["locked_margin_usd"] = round(locked_margin, 2)
        runtime_tool_states["position_margin_usd"] = round(position_margin, 2)
        runtime_tool_states["trading_balance_usd"] = round(free_collateral, 2)
        if free_collateral > 0:
            runtime_tool_states["max_order_margin_usd"] = round(free_collateral, 2)
    except Exception as exc:
        logger.debug("Failed to inject runtime balance context: %s", exc)

    return runtime_tool_states


def _build_runtime_context_block(tool_states: Optional[Dict[str, Any]]) -> List[str]:
    context = _extract_active_context(tool_states)
    if not context and not isinstance(tool_states, dict):
        return []

    write_enabled = False
    plan_enabled = False
    strict_react = False
    if isinstance(tool_states, dict):
        write_enabled = _parse_bool_flag(tool_states.get("write"), default=False)
        plan_enabled = _parse_bool_flag(tool_states.get("plan_mode"), default=False)
        strict_react = _parse_bool_flag(tool_states.get("strict_react"), default=False)

    lines: List[str] = ["[RUNTIME_CONTEXT]"]
    lines.append("source=frontend_toolbar")
    for key in (
        "market_symbol",
        "market_display",
        "timeframe",
        "timeframes",
        "conversation_style",
        "trading_style_profile",
        "trading_style_prompt",
        "account_value_usd",
        "free_collateral_usd",
        "locked_margin_usd",
        "position_margin_usd",
        "max_order_margin_usd",
    ):
        value = context.get(key)
        if value:
            lines.append(f"{key}={value}")
    lines.append(f"write_mode={'on' if write_enabled else 'off'}")
    lines.append(f"plan_mode={'on' if plan_enabled else 'off'}")
    lines.append(f"strict_react={'on' if strict_react else 'off'}")
    lines.append(
        "instruction=Treat market/timeframe above as default active scope unless user explicitly changes it."
    )
    if context.get("trading_style_profile") or context.get("trading_style_prompt"):
        lines.append(
            "style_instruction=Apply style context only for trading/TA analysis. Keep output practical and do not mention style profile names unless user asks."
        )
    if context.get("free_collateral_usd"):
        lines.append(
            "risk_instruction=When proposing or placing orders, keep amount_usd within free_collateral_usd and risk limits."
        )
    lines.append("[/RUNTIME_CONTEXT]")
    return lines


def _augment_message_with_active_context(
    message: str, tool_states: Optional[Dict[str, Any]]
) -> str:
    text = str(message or "")
    if "[RUNTIME_CONTEXT]" in text:
        return text

    lines: List[str] = []
    lines.extend(_build_runtime_context_block(tool_states))
    if lines:
        lines.append("")
    lines.append(text)
    return "\n".join(lines)


@router.post("/plan/preview")
async def agent_plan_preview(
    model_id: Optional[str] = Body(None),
    message: str = Body(...),
    history: Optional[List[Dict[str, str]]] = Body(None),
    tool_states: Optional[Dict[str, Any]] = Body(None),
    user: dict = Depends(get_current_user),
):
    """
    Build a lightweight plan preview.
    Used by frontend to show Codex-style action plan before send.
    """
    _ = user
    safe_tool_states = dict(tool_states or {})
    safe_tool_states.setdefault("planner_source", "ai")
    safe_tool_states.setdefault("planner_fallback", "none")
    if model_id:
        safe_tool_states.setdefault("planner_model_id", model_id)

    if not _is_plan_mode_enabled(safe_tool_states):
        return {
            "status": "success",
            "plan": None,
            "render": {
                "title": "AI Plan",
                "intent": "analysis",
                "steps": [],
                "warnings": [],
                "blocks": [],
            },
        }

    orchestrator = ReasoningOrchestrator()
    runtime_history = _trim_history_for_runtime(history)
    plan = orchestrator.build_plan(
        user_message=message, history=runtime_history, tool_states=safe_tool_states
    )

    steps: List[Dict[str, Any]] = []
    if plan.context.symbol:
        steps.append(
            {
                "id": "ctx_symbol",
                "label": f"Understand market context for {plan.context.symbol}",
            }
        )
    if plan.context.timeframe:
        steps.append(
            {
                "id": "ctx_timeframe",
                "label": f"Scope analysis timeframe: {plan.context.timeframe}",
            }
        )
    for idx, call in enumerate(plan.tool_calls, start=1):
        steps.append(
            {
                "id": f"tool_{idx}",
                "label": f"Use `{call.name}`",
                "reason": call.reason,
                "args": call.args,
            }
        )
    steps.append(
        {
            "id": "validate",
            "label": "Validate risk and produce concise final recommendation",
        }
    )

    return {
        "status": "success",
        "plan": asdict(plan),
        "render": {
            "title": "AI Plan",
            "intent": plan.intent,
            "steps": steps,
            "warnings": plan.warnings,
            "blocks": plan.blocks,
        },
    }


@router.get("/models")
async def list_models(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get list of AI models available to the current user.
    Sources data directly from OpenRouter for flexibility.
    """
    from services.openrouter_service import openrouter_service

    all_models = await openrouter_service.get_models()

    # Inject dynamic specialized models
    specialized = get_available_models()

    return {"models": specialized + all_models}


@router.post("/chat")
async def agent_chat(
    model_id: str = Body(...),
    message: str = Body(...),
    session_id: Optional[str] = Body(None),
    history: Optional[List[Dict[str, str]]] = Body(None),
    reasoning_effort: Optional[str] = Body(None),
    tool_states: Optional[Dict[str, Any]] = Body(None),
    attachments: Optional[List[Dict[str, Any]]] = Body(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Send a message to the AI agent.
    Checks authorization (User Settings) and handles persistent history.
    """
    user_address = _require_wallet_address(user)
    auth_user_id = user_address
    from services.ai_billing_service import ai_billing_service
    from services.chat_service import chat_service
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service

    # 0. Handle "new-chat" placeholder (force generate new ID)
    if not session_id or session_id == "new-chat":
        import uuid

        session_id = f"s-{uuid.uuid4().hex[:8]}"
    model_id = _normalize_model_id_for_runtime(model_id)

    # 1. Validate if model exists
    model_info = await openrouter_service.get_model_info(model_id)
    if not model_info:
        config = get_model_config(model_id)
        if not config:
            raise HTTPException(
                status_code=404, detail=f"Model {model_id} not found in registry."
            )
        model_info = {
            "id": model_id,
            "name": config.get("name"),
            "input_cost": config.get("input_fee", 1.0),
            "output_cost": config.get("output_fee", 2.0),
            "includes_markup": False,
        }

    # 2. Check if model is enabled
    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"

    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()

    is_groq = model_id.startswith("groq/")
    if not _is_model_enabled(model_id, enabled_models) and not is_mock and not is_groq:
        raise HTTPException(
            status_code=403, detail=f"Model {model_id} is not enabled in your settings."
        )

    if is_mock:
        print(
            f"[AgentRouter] DEBUG: Mock user detected, bypassing enablement check for {model_id}"
        )

    # 3. Save User Message
    await chat_service.save_message(
        user_address=auth_user_id,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id,
    )
    trace_ctx = langfuse_service.start_trace(
        name="agent.chat",
        user_id=auth_user_id,
        session_id=session_id,
        model_id=model_id,
        input_text=message,
        metadata={
            "reasoning_effort": reasoning_effort,
            "stream": False,
        },
    )

    # 4. Process with AgentBrain compatibility wrapper (Reflexion runtime)
    try:
        runtime_tool_states = await _inject_runtime_balance_context(
            tool_states,
            user_address=user_address,
            db=db,
        )
        ai_message = _augment_message_with_active_context(message, runtime_tool_states)
        runtime_tool_states["agent_engine"] = "reflexion"
        runtime_tool_states["agent_engine_strict"] = True
        runtime_tool_states["knowledge_enabled"] = False
        runtime_tool_states["rag_mode"] = "disabled"
        brain = AgentBrain(
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            tool_states=runtime_tool_states,
            user_context={"user_address": user_address, "session_id": session_id},
        )
        runtime_history = _trim_history_for_runtime(history)
        result = await brain.chat(
            user_message=ai_message,
            history=runtime_history,
            attachments=attachments,
        )

        response_content = result.get("content", "")
        usage = result.get("usage", {})
        thoughts = result.get("thoughts", [])
        runtime = result.get("runtime", {})

        # Calculate cost based on actual usage or fallbacks
        in_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0

        # Ensure we have integers for math
        in_tokens = int(in_tokens)
        out_tokens = int(out_tokens)

        billing = await _bill_usage_with_timeout(
            ai_billing_service,
            user_address=user_address,
            model_id=model_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            model_info=model_info,
            tool_states=runtime_tool_states,
        )
        _require_successful_billing(billing)
        total_cost = float(billing.get("total_cost_usd", 0.0))

        await _persist_ai_output(
            chat_service=chat_service,
            usage_service=usage_service,
            user_address=user_address,
            auth_user_id=auth_user_id,
            session_id=session_id,
            content=response_content,
            model_id=model_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            total_cost=total_cost,
        )

        runtime_trace_store.add(
            user_address=auth_user_id,
            session_id=session_id,
            trace={
                "model_id": model_id,
                "message": message,
                "runtime": runtime,
            },
        )
        _log_langfuse_success_async(
            trace_ctx,
            model_id=model_id,
            input_text=message,
            output_text=response_content,
            usage=usage,
            metadata={
                "runtime": runtime,
                "thoughts_count": len(thoughts or []),
                "billing_total_cost_usd": float(billing.get("total_cost_usd", 0.0)),
            },
        )

        return {
            "status": "success",
            "model": model_id,
            "session_id": session_id,
            "response": response_content,
            "usage": usage,
            "thoughts": thoughts,
            "runtime": runtime,
            "billing": billing,
        }
    except HTTPException as e:
        _log_langfuse_error_async(
            trace_ctx,
            model_id=model_id,
            input_text=message,
            error_message=str(e.detail),
            metadata={"reasoning_effort": reasoning_effort, "stream": False},
        )
        raise
    except Exception as e:
        _log_langfuse_error_async(
            trace_ctx,
            model_id=model_id,
            input_text=message,
            error_message=str(e),
            metadata={"reasoning_effort": reasoning_effort, "stream": False},
        )
        raise HTTPException(status_code=500, detail=f"AI Agent Error: {str(e)}")


class ChatInterruptRequest(BaseModel):
    session_id: str


@router.post("/chat/interrupt")
async def agent_chat_interrupt(
    payload: ChatInterruptRequest,
    user: dict = Depends(get_current_user),
):
    user_address = _require_wallet_address(user)
    auth_user_id = user_address

    session_id = str(payload.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    interrupted = _interrupt_active_stream(auth_user_id, session_id)
    return {
        "status": "success",
        "session_id": session_id,
        "interrupted": interrupted,
    }


@router.post("/chat/stream")
async def agent_chat_stream(
    model_id: str = Body(...),
    message: str = Body(...),
    session_id: Optional[str] = Body(None),
    history: Optional[List[Dict[str, str]]] = Body(None),
    reasoning_effort: Optional[str] = Body(None),
    tool_states: Optional[Dict[str, Any]] = Body(None),
    attachments: Optional[List[Dict[str, Any]]] = Body(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream a message to the AI agent.
    Emits Server-Sent Events (SSE).
    """
    user_address = _require_wallet_address(user)
    auth_user_id = user_address
    from services.ai_billing_service import ai_billing_service
    from services.chat_service import chat_service
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service

    if not session_id or session_id == "new-chat":
        import uuid

        session_id = f"s-{uuid.uuid4().hex[:8]}"
    model_id = _normalize_model_id_for_runtime(model_id)

    model_info = await openrouter_service.get_model_info(model_id)
    if not model_info:
        config = get_model_config(model_id)
        if not config:
            raise HTTPException(
                status_code=404, detail=f"Model {model_id} not found in registry."
            )
        model_info = {
            "id": model_id,
            "name": config.get("name"),
            "input_cost": config.get("input_fee", 1.0),
            "output_cost": config.get("output_fee", 2.0),
            "includes_markup": False,
        }

    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"
    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()

    is_groq = model_id.startswith("groq/")
    if not _is_model_enabled(model_id, enabled_models) and not is_mock and not is_groq:
        raise HTTPException(
            status_code=403, detail=f"Model {model_id} is not enabled in your settings."
        )

    await chat_service.save_message(
        user_address=auth_user_id,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id,
    )
    trace_ctx = langfuse_service.start_trace(
        name="agent.chat.stream",
        user_id=auth_user_id,
        session_id=session_id,
        model_id=model_id,
        input_text=message,
        metadata={
            "reasoning_effort": reasoning_effort,
            "stream": True,
        },
    )

    async def event_stream():
        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        stream_task = asyncio.current_task()
        _register_active_stream(auth_user_id, session_id, stream_task)

        try:
            yield sse({"type": "meta", "session_id": session_id, "model": model_id})

            runtime_tool_states = await _inject_runtime_balance_context(
                tool_states,
                user_address=user_address,
                db=db,
            )
            ai_message = _augment_message_with_active_context(
                message, runtime_tool_states
            )
            runtime_tool_states["agent_engine"] = "reflexion"
            runtime_tool_states["agent_engine_strict"] = True
            runtime_tool_states["knowledge_enabled"] = False
            runtime_tool_states["rag_mode"] = "disabled"
            brain = AgentBrain(
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                tool_states=runtime_tool_states,
                user_context={"user_address": user_address, "session_id": session_id},
            )
            runtime_history = _trim_history_for_runtime(history)
            full_content_parts: List[str] = []
            thoughts: List[str] = []
            usage: Dict[str, Any] = {}
            runtime: Dict[str, Any] = {}
            saw_done_event = False
            saw_error_event = False

            try:
                model_timeout_raw: Any = None
                if isinstance(runtime_tool_states, dict):
                    model_timeout_raw = runtime_tool_states.get("model_timeout_sec")
                try:
                    model_timeout_sec = (
                        float(model_timeout_raw)
                        if model_timeout_raw is not None
                        else DEFAULT_CHAT_STREAM_TIMEOUT_SECONDS
                    )
                except Exception:
                    model_timeout_sec = DEFAULT_CHAT_STREAM_TIMEOUT_SECONDS
                stream_timeout_sec = max(
                    DEFAULT_CHAT_STREAM_TIMEOUT_SECONDS,
                    min(model_timeout_sec, MAX_CHAT_STREAM_TIMEOUT_SECONDS),
                )

                async with asyncio.timeout(stream_timeout_sec):
                    async for event in brain.stream(
                        user_message=ai_message,
                        history=runtime_history,
                        attachments=attachments,
                    ):
                        if event.get("type") == "delta":
                            full_content_parts.append(event.get("content", ""))
                        elif event.get("type") == "thoughts":
                            thoughts = event.get("thoughts", [])
                        elif event.get("type") == "runtime":
                            runtime = event.get("runtime", {}) or {}
                        elif event.get("type") == "done":
                            saw_done_event = True
                            usage = event.get("usage", {}) or {}
                            if isinstance(event.get("thoughts"), list):
                                thoughts = event.get("thoughts", [])
                        elif event.get("type") == "error":
                            saw_error_event = True

                        # Hold terminal done until billing succeeds.
                        if event.get("type") == "done":
                            continue

                        yield sse(event)
            except asyncio.TimeoutError:
                yield sse(
                    {
                        "type": "error",
                        "message": (
                            f"AI stream timeout after {int(stream_timeout_sec)}s. "
                            "Please retry with simpler prompt or lower tool scope."
                        ),
                    }
                )
                return

            if saw_error_event:
                return

            full_content = "".join(full_content_parts)

            in_tokens = int(
                usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            )
            out_tokens = int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )

            billing = await _bill_usage_with_timeout(
                ai_billing_service,
                user_address=user_address,
                model_id=model_id,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                model_info=model_info,
                tool_states=runtime_tool_states,
            )
            _require_successful_billing(billing)
            total_cost = float(billing.get("total_cost_usd", 0.0))

            await _persist_ai_output(
                chat_service=chat_service,
                usage_service=usage_service,
                user_address=user_address,
                auth_user_id=auth_user_id,
                session_id=session_id,
                content=full_content,
                model_id=model_id,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                total_cost=total_cost,
            )

            runtime_trace_store.add(
                user_address=auth_user_id,
                session_id=session_id,
                trace={
                    "model_id": model_id,
                    "message": message,
                    "runtime": runtime,
                },
            )
            _log_langfuse_success_async(
                trace_ctx,
                model_id=model_id,
                input_text=message,
                output_text=full_content,
                usage=usage,
                metadata={
                    "runtime": runtime,
                    "thoughts_count": len(thoughts or []),
                    "billing_total_cost_usd": float(billing.get("total_cost_usd", 0.0)),
                    "stream": True,
                },
            )
            yield sse({"type": "billing", "billing": billing})
            yield sse(
                {
                    "type": "done",
                    "content": full_content,
                    "usage": usage or {},
                    "thoughts": thoughts or [],
                }
            )

        except asyncio.CancelledError:
            raise
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else "Billing failed"
            _log_langfuse_error_async(
                trace_ctx,
                model_id=model_id,
                input_text=message,
                error_message=detail,
                metadata={"reasoning_effort": reasoning_effort, "stream": True},
            )
            yield sse({"type": "error", "message": detail})
        except Exception as e:
            _log_langfuse_error_async(
                trace_ctx,
                model_id=model_id,
                input_text=message,
                error_message=str(e),
                metadata={"reasoning_effort": reasoning_effort, "stream": True},
            )
            yield sse({"type": "error", "message": f"AI Agent Error: {str(e)}"})
        finally:
            _unregister_active_stream(auth_user_id, session_id, stream_task)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def get_my_sessions(limit: int = 20, user: dict = Depends(get_current_user)):
    """Get recent chat sessions for the current user"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    return await chat_service.get_user_sessions(user_address, limit)


@router.get("/history/{session_id}")
async def get_chat_history(session_id: str, user: dict = Depends(get_current_user)):
    """Get messages for a specific session"""
    from services.chat_service import chat_service

    # Optional: Validate ownership here if needed
    return await chat_service.get_session_history(session_id)


@router.get("/runtime-trace/{session_id}")
async def get_runtime_trace(
    session_id: str, limit: int = 20, user: dict = Depends(get_current_user)
):
    """Get recent runtime traces (plan/tool outputs) for a chat session."""
    user_address = _require_wallet_address(user)
    return {
        "status": "success",
        "session_id": session_id,
        "traces": runtime_trace_store.list(
            user_address=user_address, session_id=session_id, limit=limit
        ),
    }


@router.patch("/session/{session_id}")
async def update_session_title(
    session_id: str,
    title: str = Body(..., embed=True),
    user: dict = Depends(get_current_user),
):
    """Update session title (rename)"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    success = await chat_service.update_session(session_id, user_address, title)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update session title")
    return {"status": "success"}


@router.delete("/session/{session_id}")
async def delete_chat_session(session_id: str, user: dict = Depends(get_current_user)):
    """Delete a chat session and its history"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    success = await chat_service.delete_session(session_id, user_address)
    if not success:
        raise HTTPException(
            status_code=403,
            detail="Failed to delete session (unauthorized or not found)",
        )
    return {"status": "success"}


# --- Workspace Endpoints ---


@router.get("/workspaces")
async def get_workspaces(user: dict = Depends(get_current_user)):
    """Get all workspaces for the current user"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    return await chat_service.get_user_workspaces(user_address)


class WorkspaceCreateRequest(BaseModel):
    name: str
    workspace_id: Optional[str] = None


@router.post("/workspaces")
async def create_workspace(
    request: WorkspaceCreateRequest, user: dict = Depends(get_current_user)
):
    """Create a new workspace"""
    import uuid

    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    ws_id = request.workspace_id or f"ws-{uuid.uuid4().hex[:8]}"
    success = await chat_service.create_workspace(user_address, ws_id, request.name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create workspace")
    return {"status": "success", "id": ws_id}


@router.patch("/session/{session_id}/move")
async def move_session(
    session_id: str,
    workspace_id: Optional[str] = Body(None, embed=True),
    user: dict = Depends(get_current_user),
):
    """Move session to a workspace (or null for inbox)"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    success = await chat_service.move_session(session_id, user_address, workspace_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to move session")
    return {"status": "success"}


@router.patch("/workspace/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    name: Optional[str] = Body(None),
    icon: Optional[str] = Body(None),
    is_expanded: Optional[bool] = Body(None),
    user: dict = Depends(get_current_user),
):
    """Update workspace properties"""
    from services.chat_service import chat_service

    user_address = _require_wallet_address(user)
    success = await chat_service.update_workspace(
        workspace_id, user_address, name=name, icon=icon, is_expanded=is_expanded
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update workspace")
    return {"status": "success"}
