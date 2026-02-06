import logging
from typing import List, Optional, Dict, Any
from sqlalchemy import select, desc
from database.models import ChatSession, ChatMessage, ChatWorkspace
from database.connection import AsyncSessionLocal
from datetime import datetime

logger = logging.getLogger(__name__)

class ChatService:
    """Service to handle chat sessions and message persistence"""

    async def get_or_create_session(self, user_address: str, session_id: str, model_id: Optional[str] = None) -> ChatSession:
        """Get existing session or create a new one"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession).filter(ChatSession.id == session_id)
            )
            chat_session = result.scalars().first()

            if not chat_session:
                chat_session = ChatSession(
                    id=session_id,
                    user_address=user_address,
                    model_id=model_id,
                    title="New Chat"
                )
                session.add(chat_session)
                await session.commit()
                await session.refresh(chat_session)
            elif model_id:
                chat_session.model_id = model_id
                chat_session.updated_at = datetime.utcnow()
                await session.commit()

            return chat_session

    async def save_message(
        self, 
        user_address: str, 
        session_id: str, 
        role: str, 
        content: str, 
        model_id: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0
    ):
        """Save a message to the database and update session timestamp"""
        async with AsyncSessionLocal() as session:
            try:
                # 1. Ensure session exists
                await self.get_or_create_session(user_address, session_id, model_id)
                
                # 2. Save message
                message = ChatMessage(
                    session_id=session_id,
                    user_address=user_address,
                    role=role,
                    content=content,
                    model_id=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost
                )
                session.add(message)
                
                # 3. Update session's updated_at
                await session.execute(
                    ChatSession.__table__.update()
                    .where(ChatSession.id == session_id)
                    .values(updated_at=datetime.utcnow())
                )
                
                await session.commit()
            except Exception as e:
                logger.error(f"Error saving chat message: {e}")
                await session.rollback()

    async def get_session_history(self, session_id: str, limit: int = 100) -> List[Dict[str, str]]:
        """Retrieve recent messages for a session formatted for LLM history"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.timestamp.asc())
                .limit(limit)
            )
            messages = result.scalars().all()
            return [{"role": msg.role, "content": msg.content} for msg in messages]

    async def get_user_sessions(self, user_address: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get all chat sessions for a user"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession)
                .filter(ChatSession.user_address == user_address)
                .order_by(desc(ChatSession.updated_at))
                .limit(limit)
            )
            sessions = result.scalars().all()
            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "model_id": s.model_id,
                    "workspace_id": s.workspace_id,
                    "updated_at": (s.updated_at or s.created_at or datetime.utcnow()).isoformat()
                }
                for s in sessions
            ]

    async def delete_session(self, session_id: str, user_address: str):
        """Delete a chat session and all its messages"""
        async with AsyncSessionLocal() as session:
            try:
                # Security: ensure user owns the session
                result = await session.execute(
                    select(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_address == user_address)
                )
                if not result.scalars().first():
                    return False
                
                # Delete messages first (or let cascade handle if configured, but we do it manually for safety)
                from sqlalchemy import delete
                await session.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
                await session.execute(delete(ChatSession).where(ChatSession.id == session_id))
                
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error deleting session: {e}")
                await session.rollback()
                return False

    async def update_session(self, session_id: str, user_address: str, title: str) -> bool:
        """Update session title"""
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    ChatSession.__table__.update()
                    .where(ChatSession.id == session_id, ChatSession.user_address == user_address)
                    .values(title=title, updated_at=datetime.utcnow())
                )
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating session: {e}")
                await session.rollback()
                return False

    # --- Workspace Methods ---

    async def get_user_workspaces(self, user_address: str) -> List[Dict[str, Any]]:
        """Get all workspaces for a user"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatWorkspace)
                .filter(ChatWorkspace.user_address == user_address)
                .order_by(ChatWorkspace.created_at.asc())
            )
            workspaces = result.scalars().all()
            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "icon": w.icon,
                    "is_expanded": w.is_expanded
                }
                for w in workspaces
            ]

    async def create_workspace(self, user_address: str, workspace_id: str, name: str) -> bool:
        """Create a new workspace"""
        async with AsyncSessionLocal() as session:
            try:
                ws = ChatWorkspace(
                    id=workspace_id,
                    user_address=user_address,
                    name=name
                )
                session.add(ws)
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error creating workspace: {e}")
                await session.rollback()
                return False

    async def move_session(self, session_id: str, user_address: str, workspace_id: Optional[str]) -> bool:
        """Move a chat session to a different workspace (or NULL for Inbox)"""
        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    ChatSession.__table__.update()
                    .where(ChatSession.id == session_id, ChatSession.user_address == user_address)
                    .values(workspace_id=workspace_id, updated_at=datetime.utcnow())
                )
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error moving session: {e}")
                await session.rollback()
                return False

    async def update_workspace(self, workspace_id: str, user_address: str, **kwargs) -> bool:
        """Update workspace properties (name, icon, is_expanded)"""
        async with AsyncSessionLocal() as session:
            try:
                # Filter out None values and updated_at
                update_data = {k: v for k, v in kwargs.items() if v is not None}
                if not update_data: return True
                
                update_data['updated_at'] = datetime.utcnow()
                
                await session.execute(
                    ChatWorkspace.__table__.update()
                    .where(ChatWorkspace.id == workspace_id, ChatWorkspace.user_address == user_address)
                    .values(**update_data)
                )
                await session.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating workspace: {e}")
                await session.rollback()
                return False

chat_service = ChatService()
