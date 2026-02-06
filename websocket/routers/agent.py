"""
Agent API Router
Handles AI Chat interactions and model discovery.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from auth.dependencies import get_current_user
from database.connection import get_db
from sqlalchemy.orm import Session
from services.portfolio_service import PortfolioService
from agent.Core.agent_brain import AgentBrain
from agent.Config.models_config import get_available_models, get_model_config

router = APIRouter(
    tags=["Agent"]
)

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
    user_address = user.get("sub")
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service
    from services.chat_service import chat_service
    
    # 0. Handle "new-chat" placeholder (force generate new ID)
    if not session_id or session_id == "new-chat":
        import uuid
        session_id = f"s-{uuid.uuid4().hex[:8]}"

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
            "output_cost": config.get("output_fee", 2.0)
        }
    
    # 2. Check if model is enabled
    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"
    
    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()
        
    is_groq = model_id.startswith("groq/")
    if model_id not in enabled_models and not is_mock and not is_groq:
        raise HTTPException(
            status_code=403, 
            detail=f"Model {model_id} is not enabled in your settings."
        )
    
    if is_mock:
        print(f"[AgentRouter] DEBUG: Mock user detected, bypassing enablement check for {model_id}")
        
    # 3. Save User Message
    await chat_service.save_message(
        user_address=user_address,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id
    )

    # 4. Process with AgentBrain
    try:
        input_fee = model_info.get("input_cost", 1.0)
        output_fee = model_info.get("output_cost" , 2.0)

        brain = AgentBrain(model_id=model_id, reasoning_effort=reasoning_effort, tool_states=tool_states)
        result = await brain.chat(user_message=message, history=history, attachments=attachments)
        
        response_content = result.get("content", "")
        usage = result.get("usage", {})
        thoughts = result.get("thoughts", [])
        
        # Calculate cost based on actual usage or fallbacks
        in_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        
        # Ensure we have integers for math
        in_tokens = int(in_tokens)
        out_tokens = int(out_tokens)
        
        # Mock cost calculation
        total_cost = (in_tokens / 1_000_000 * input_fee) + (out_tokens / 1_000_000 * output_fee)
        if total_cost == 0 and (in_tokens > 0 or out_tokens > 0):
            total_cost = 0.001 # Minimum floor for real usage

        # 5. Save AI Response
        await chat_service.save_message(
            user_address=user_address,
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
        
        return {
            "status": "success",
            "model": model_id,
            "session_id": session_id,
            "response": response_content,
            "usage": usage,
            "thoughts": thoughts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent Error: {str(e)}")

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
    user_address = user.get("sub")
    from services.openrouter_service import openrouter_service
    from services.usage_service import usage_service
    from services.chat_service import chat_service

    if not session_id or session_id == "new-chat":
        import uuid
        session_id = f"s-{uuid.uuid4().hex[:8]}"

    model_info = await openrouter_service.get_model_info(model_id)
    if not model_info:
        config = get_model_config(model_id)
        if not config:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found in registry.")
        model_info = {
            "id": model_id,
            "name": config.get("name"),
            "input_cost": config.get("input_fee", 1.0),
            "output_cost": config.get("output_fee", 2.0)
        }

    is_mock = user_address.startswith("0x") and user.get("name") == "Test User"
    enabled_models = await usage_service.get_enabled_models(user_address)
    if not enabled_models:
        enabled_models = await usage_service.get_default_enabled_models()

    is_groq = model_id.startswith("groq/")
    if model_id not in enabled_models and not is_mock and not is_groq:
        raise HTTPException(
            status_code=403,
            detail=f"Model {model_id} is not enabled in your settings."
        )

    await chat_service.save_message(
        user_address=user_address,
        session_id=session_id,
        role="user",
        content=message,
        model_id=model_id
    )

    async def event_stream():
        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            yield sse({"type": "meta", "session_id": session_id, "model": model_id})

            input_fee = model_info.get("input_cost", 1.0)
            output_fee = model_info.get("output_cost", 2.0)

            brain = AgentBrain(model_id=model_id, reasoning_effort=reasoning_effort, tool_states=tool_states)
            full_content = ""
            thoughts: List[str] = []
            usage: Dict[str, Any] = {}

            async for event in brain.stream(user_message=message, history=history, attachments=attachments):
                if event.get("type") == "delta":
                    full_content += event.get("content", "")
                elif event.get("type") == "thoughts":
                    thoughts = event.get("thoughts", [])
                elif event.get("type") == "done":
                    usage = event.get("usage", {}) or {}

                yield sse(event)

            in_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

            total_cost = (in_tokens / 1_000_000 * input_fee) + (out_tokens / 1_000_000 * output_fee)
            if total_cost == 0 and (in_tokens > 0 or out_tokens > 0):
                total_cost = 0.001

            await chat_service.save_message(
                user_address=user_address,
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

        except Exception as e:
            yield sse({"type": "error", "message": f"AI Agent Error: {str(e)}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.get("/sessions")
async def get_my_sessions(
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    """Get recent chat sessions for the current user"""
    from services.chat_service import chat_service
    user_address = user.get("sub")
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

@router.patch("/session/{session_id}")
async def update_session_title(
    session_id: str,
    title: str = Body(..., embed=True),
    user: dict = Depends(get_current_user)
):
    """Update session title (rename)"""
    from services.chat_service import chat_service
    user_address = user.get("sub")
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
    user_address = user.get("sub")
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
    user_address = user.get("sub")
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
    user_address = user.get("sub")
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
    user_address = user.get("sub")
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
    user_address = user.get("sub")
    success = await chat_service.update_workspace(
        workspace_id, user_address, 
        name=name, icon=icon, is_expanded=is_expanded
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update workspace")
    return {"status": "success"}
