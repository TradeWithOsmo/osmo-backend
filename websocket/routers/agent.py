"""
Agent API Router
Handles AI Chat interactions and model discovery.
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
import json
from dataclasses import asdict
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from auth.dependencies import get_current_user
from database.connection import get_db
from sqlalchemy.orm import Session
from services.portfolio_service import PortfolioService
from services.langfuse_service import langfuse_service
from agent.Core.agent_brain import AgentBrain
from agent.Config.models_config import get_available_models, get_model_config
try:
    from agent.Orchestrator.trace_store import runtime_trace_store
except Exception:
    from backend.agent.Orchestrator.trace_store import runtime_trace_store
try:
    from agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator
except Exception:
    from backend.agent.Orchestrator.reasoning_orchestrator import ReasoningOrchestrator

router = APIRouter(
    tags=["Agent"]
)

_ACTIVE_STREAMS: Dict[tuple[str, str], asyncio.Task] = {}


def _stream_key(user_id: str, session_id: str) -> tuple[str, str]:
    return (str(user_id or "").strip(), str(session_id or "").strip())


def _register_active_stream(user_id: str, session_id: str, task: Optional[asyncio.Task]) -> None:
    if task is None:
        return
    key = _stream_key(user_id, session_id)
    if not key[0] or not key[1]:
        return
    _ACTIVE_STREAMS[key] = task


def _unregister_active_stream(user_id: str, session_id: str, task: Optional[asyncio.Task] = None) -> None:
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

def _model_base_id(model_id: Optional[str]) -> str:
    raw = (model_id or "").strip()
    return raw.split(":", 1)[0] if raw else ""

def _normalize_model_id_for_runtime(model_id: str) -> str:
    """
    Normalize legacy provider prefixes so runtime stays OpenRouter-first.
    """
    raw = str(model_id or "").strip()
    if "/" not in raw:
        return raw
    prefix, remainder = raw.split("/", 1)
    if prefix.lower() in {"nvidia", "openrouter"} and remainder:
        return remainder
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
    return payload


def _parse_bool_flag(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no"}
    return bool(value)


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
    for key in ("market_symbol", "market_display", "timeframe", "timeframes"):
        value = context.get(key)
        if value:
            lines.append(f"{key}={value}")
    lines.append(f"write_mode={'on' if write_enabled else 'off'}")
    lines.append(f"plan_mode={'on' if plan_enabled else 'off'}")
    lines.append(f"strict_react={'on' if strict_react else 'off'}")
    lines.append("instruction=Treat market/timeframe above as default active scope unless user explicitly changes it.")
    lines.append("[/RUNTIME_CONTEXT]")
    return lines


def _augment_message_with_active_context(message: str, tool_states: Optional[Dict[str, Any]]) -> str:
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
    plan = orchestrator.build_plan(user_message=message, history=history, tool_states=safe_tool_states)

    steps: List[Dict[str, Any]] = []
    if plan.context.symbol:
        steps.append({"id": "ctx_symbol", "label": f"Understand market context for {plan.context.symbol}"})
    if plan.context.timeframe:
        steps.append({"id": "ctx_timeframe", "label": f"Scope analysis timeframe: {plan.context.timeframe}"})
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
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of AI models available to the current user.
    Sources data directly from OpenRouter for flexibility.
    """
    from services.openrouter_service import openrouter_service
    all_models = await openrouter_service.get_models()
    
    # Inject dynamic specialized models
    specialized = get_available_models()
    
    return {
        "models": specialized + all_models
    }

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
    db: Session = Depends(get_db)
):
    """
    Send a message to the AI agent.
    Checks authorization (User Settings) and handles persistent history.
    """
    user_address = _require_wallet_address(user)
    auth_user_id = user_address
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service
    from services.chat_service import chat_service
    from services.ai_billing_service import ai_billing_service

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
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found in registry.")
        model_info = {
            "id": model_id,
            "name": config.get("name"),
            "input_cost": config.get("input_fee", 1.0),
            "output_cost": config.get("output_fee", 2.0),
            "includes_markup": False
        }
    
    # 2. Check if model is enabled
    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"
    
    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()
        
    is_groq = model_id.startswith("groq/")
    is_free_model = model_id.endswith(":free")
    if not _is_model_enabled(model_id, enabled_models) and not is_mock and not is_groq and not is_free_model:
        raise HTTPException(
            status_code=403, 
            detail=f"Model {model_id} is not enabled in your settings."
        )
    
    if is_mock:
        print(f"[AgentRouter] DEBUG: Mock user detected, bypassing enablement check for {model_id}")
        
    # 3. Save User Message
    await chat_service.save_message(
        user_address=auth_user_id,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id
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

    # 4. Process with AgentBrain
    try:
        ai_message = _augment_message_with_active_context(message, tool_states)
        runtime_tool_states = dict(tool_states or {})
        runtime_tool_states["agent_engine"] = "deepagents"
        runtime_tool_states["agent_engine_strict"] = True
        runtime_tool_states["knowledge_enabled"] = True
        runtime_tool_states["rag_mode"] = "secondary"
        brain = AgentBrain(
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            tool_states=runtime_tool_states,
            user_context={"user_address": user_address, "session_id": session_id},
        )
        result = await brain.chat(user_message=ai_message, history=history, attachments=attachments)
        
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
        
        billing = await ai_billing_service.bill_usage(
            user_address=user_address,
            model_id=model_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            model_info=model_info
        )
        total_cost = float(billing.get("total_cost_usd", 0.0))

        # 5. Save AI Response
        await chat_service.save_message(
            user_address=auth_user_id,
            session_id=session_id,
            role="assistant",
            content=response_content,
            model_id=model_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost=total_cost
        )

        # 6. Log to Global Usage (Async background-like)
        await usage_service.log_usage(
            user_address=user_address,
            model=model_id,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost=total_cost,
            session_id=session_id
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
        langfuse_service.log_success(
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
            "billing": billing
        }
    except Exception as e:
        langfuse_service.log_error(
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
    db: Session = Depends(get_db)
):
    """
    Stream a message to the AI agent.
    Emits Server-Sent Events (SSE).
    """
    user_address = _require_wallet_address(user)
    auth_user_id = user_address
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service
    from services.chat_service import chat_service
    from services.ai_billing_service import ai_billing_service

    if not session_id or session_id == "new-chat":
        import uuid
        session_id = f"s-{uuid.uuid4().hex[:8]}"
    model_id = _normalize_model_id_for_runtime(model_id)

    model_info = await openrouter_service.get_model_info(model_id)
    if not model_info:
        config = get_model_config(model_id)
        if not config:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found in registry.")
        model_info = {
            "id": model_id,
            "name": config.get("name"),
            "input_cost": config.get("input_fee", 1.0),
            "output_cost": config.get("output_fee", 2.0),
            "includes_markup": False
        }

    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"
    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()

    is_groq = model_id.startswith("groq/")
    is_free_model = model_id.endswith(":free")
    if not _is_model_enabled(model_id, enabled_models) and not is_mock and not is_groq and not is_free_model:
        raise HTTPException(
            status_code=403,
            detail=f"Model {model_id} is not enabled in your settings."
        )

    await chat_service.save_message(
        user_address=auth_user_id,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id
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

            ai_message = _augment_message_with_active_context(message, tool_states)
            runtime_tool_states = dict(tool_states or {})
            runtime_tool_states["agent_engine"] = "deepagents"
            runtime_tool_states["agent_engine_strict"] = True
            runtime_tool_states["knowledge_enabled"] = True
            runtime_tool_states["rag_mode"] = "secondary"
            brain = AgentBrain(
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                tool_states=runtime_tool_states,
                user_context={"user_address": user_address, "session_id": session_id},
            )
            full_content = ""
            thoughts: List[str] = []
            usage: Dict[str, Any] = {}
            runtime: Dict[str, Any] = {}
            saw_done_event = False
            saw_error_event = False

            try:
                model_timeout_raw: Any = None
                if isinstance(tool_states, dict):
                    model_timeout_raw = tool_states.get("model_timeout_sec")
                try:
                    model_timeout_sec = float(model_timeout_raw) if model_timeout_raw is not None else 120.0
                except Exception:
                    model_timeout_sec = 120.0
                stream_timeout_sec = max(30.0, min(model_timeout_sec + 30.0, 360.0))

                async with asyncio.timeout(stream_timeout_sec):
                    async for event in brain.stream(user_message=ai_message, history=history, attachments=attachments):
                        if event.get("type") == "delta":
                            full_content += event.get("content", "")
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

            if not saw_done_event:
                yield sse(
                    {
                        "type": "done",
                        "content": full_content,
                        "usage": usage or {},
                        "thoughts": thoughts or [],
                    }
                )

            in_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

            billing = await ai_billing_service.bill_usage(
                user_address=user_address,
                model_id=model_id,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                model_info=model_info
            )
            total_cost = float(billing.get("total_cost_usd", 0.0))

            await chat_service.save_message(
                user_address=auth_user_id,
                session_id=session_id,
                role="assistant",
                content=full_content,
                model_id=model_id,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost=total_cost
            )

            await usage_service.log_usage(
                user_address=user_address,
                model=model_id,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost=total_cost,
                session_id=session_id
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
            langfuse_service.log_success(
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

        except asyncio.CancelledError:
            raise
        except Exception as e:
            langfuse_service.log_error(
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
async def get_my_sessions(
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    """Get recent chat sessions for the current user"""
    from services.chat_service import chat_service
    user_address = _require_wallet_address(user)
    return await chat_service.get_user_sessions(user_address, limit)

@router.get("/history/{session_id}")
async def get_chat_history(
    session_id: str,
    user: dict = Depends(get_current_user)
):
    """Get messages for a specific session"""
    from services.chat_service import chat_service
    # Optional: Validate ownership here if needed
    return await chat_service.get_session_history(session_id)

@router.get("/runtime-trace/{session_id}")
async def get_runtime_trace(
    session_id: str,
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    """Get recent runtime traces (plan/tool outputs) for a chat session."""
    user_address = _require_wallet_address(user)
    return {
        "status": "success",
        "session_id": session_id,
        "traces": runtime_trace_store.list(user_address=user_address, session_id=session_id, limit=limit),
    }

@router.patch("/session/{session_id}")
async def update_session_title(
    session_id: str,
    title: str = Body(..., embed=True),
    user: dict = Depends(get_current_user)
):
    """Update session title (rename)"""
    from services.chat_service import chat_service
    user_address = _require_wallet_address(user)
    success = await chat_service.update_session(session_id, user_address, title)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update session title")
    return {"status": "success"}

@router.delete("/session/{session_id}")
async def delete_chat_session(
    session_id: str,
    user: dict = Depends(get_current_user)
):
    """Delete a chat session and its history"""
    from services.chat_service import chat_service
    user_address = _require_wallet_address(user)
    success = await chat_service.delete_session(session_id, user_address)
    if not success:
        raise HTTPException(status_code=403, detail="Failed to delete session (unauthorized or not found)")
    return {"status": "success"}

# --- Workspace Endpoints ---

@router.get("/workspaces")
async def get_workspaces(
    user: dict = Depends(get_current_user)
):
    """Get all workspaces for the current user"""
    from services.chat_service import chat_service
    user_address = _require_wallet_address(user)
    return await chat_service.get_user_workspaces(user_address)

class WorkspaceCreateRequest(BaseModel):
    name: str
    workspace_id: Optional[str] = None

@router.post("/workspaces")
async def create_workspace(
    request: WorkspaceCreateRequest,
    user: dict = Depends(get_current_user)
):
    """Create a new workspace"""
    from services.chat_service import chat_service
    import uuid
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
    user: dict = Depends(get_current_user)
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
    user: dict = Depends(get_current_user)
):
    """Update workspace properties"""
    from services.chat_service import chat_service
    user_address = _require_wallet_address(user)
    success = await chat_service.update_workspace(
        workspace_id, user_address, 
        name=name, icon=icon, is_expanded=is_expanded
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update workspace")
    return {"status": "success"}
