from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import text, desc
from datetime import datetime, timedelta
import json
import collections
import time
import re
from storage.redis_manager import redis_manager

active_users_by_symbol = collections.defaultdict(dict)
from database import models
from database.connection import AsyncSessionLocal

router = APIRouter()


def _normalize_chat_symbol(raw_symbol: str) -> str:
    """
    Normalize chat room scope to base symbol only.
    Examples:
    - BTC-USD, BTC/USDT, btc_usdc -> BTC
    - ETH -> ETH
    """
    raw = str(raw_symbol or "").strip().upper()
    if not raw:
        return "GLOBAL"
    cleaned = re.sub(r"[^A-Z0-9/_-]", "", raw)
    if not cleaned:
        return "GLOBAL"
    for sep in ("-", "/", "_"):
        if sep in cleaned:
            base = cleaned.split(sep, 1)[0].strip()
            return base or "GLOBAL"
    return cleaned

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def cleanup_old_messages(db):
    """Delete messages older than 24 hours (UTC) to keep the DB light."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    await db.execute(
        text("DELETE FROM global_chat_messages WHERE timestamp < :cutoff"),
        {"cutoff": cutoff}
    )
    await db.commit()

@router.get("/global")
async def get_global_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    symbol: str = Query("Global", description="Chat room symbol"),
    limit: int = Query(50, le=200),
    db = Depends(get_db)
):
    """
    Get recent global chat messages.
    Automatically triggers cleanup of messages older than 24h UTC.
    """
    # Trigger cleanup in background
    background_tasks.add_task(cleanup_old_messages, db)
    
    # Also restrict the query just in case cleanup hasn't run yet
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    room_symbol = _normalize_chat_symbol(symbol)
    query = text("""
        SELECT * FROM global_chat_messages 
        WHERE timestamp >= :cutoff
          AND (symbol = :symbol OR symbol LIKE :legacy_prefix)
        ORDER BY timestamp ASC 
        LIMIT :limit
    """)
    
    result = await db.execute(
        query,
        {
            "cutoff": cutoff,
            "symbol": room_symbol,
            "legacy_prefix": f"{room_symbol}-%",
            "limit": limit,
        },
    )
    rows = result.fetchall()
    
    messages = []
    for row in rows:
        messages.append({
            "id": row.id,
            "address": row.address,
            "text": row.text,
            "timestamp": row.timestamp.isoformat(),
            "images": json.loads(row.images) if row.images else [],
            "replyTo": json.loads(row.reply_to) if row.reply_to else None,
            "sharedNews": json.loads(row.shared_news) if row.shared_news else None,
        })
    
    # Track online users using IP and timestamp per symbol
    ip = request.client.host if request.client else "unknown"
    now_ts = time.time()
    
    room_users = active_users_by_symbol[room_symbol]
    room_users[ip] = now_ts
    
    # Clean up older than 15s and count
    expired_ips = [k for k, v in room_users.items() if now_ts - v > 15]
    for k in expired_ips:
        del room_users[k]
        
    online_count = max(1, len(room_users))
        
    return {
        "messages": messages,
        "online_count": online_count,
        "symbol": room_symbol,
    }

@router.post("/global")
async def post_global_chat(
    message: dict,
    background_tasks: BackgroundTasks,
    db = Depends(get_db)
):
    """
    Post a new global chat message.
    Automatically triggers cleanup of messages older than 24h UTC.
    """
    # Trigger cleanup in background
    background_tasks.add_task(cleanup_old_messages, db)
    
    symbol = _normalize_chat_symbol(message.get("symbol", "Global"))
    address = message.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="Address is required")
        
    text_content = message.get("text", "")
    images = message.get("images", [])
    reply_to = message.get("replyTo")
    shared_news = message.get("sharedNews")
    
    query = text("""
        INSERT INTO global_chat_messages 
        (symbol, address, text, images, reply_to, shared_news, timestamp) 
        VALUES (:symbol, :address, :text, :images, :reply_to, :shared_news, :timestamp)
        RETURNING id
    """)
    
    timestamp = datetime.utcnow()
    
    result = await db.execute(query, {
        "symbol": symbol,
        "address": address,
        "text": text_content,
        "images": json.dumps(images) if images else None,
        "reply_to": json.dumps(reply_to) if reply_to else None,
        "shared_news": json.dumps(shared_news) if shared_news else None,
        "timestamp": timestamp
    })
    
    new_id = result.scalar_one()
    await db.commit()

    # Push real-time reply notification to the original message author.
    # Trigger only when sender replies to someone else.
    if reply_to and isinstance(reply_to, dict):
        target_address = str(reply_to.get("address") or "").strip().lower()
        if target_address and target_address != address.lower():
            try:
                await redis_manager.publish(
                    f"user_notifications:{target_address}",
                    {
                        "type": "chat_reply",
                        "address": target_address,
                        "timestamp": timestamp.isoformat(),
                        "data": {
                            "symbol": symbol,
                            "from_address": address,
                            "message": text_content,
                            "reply_to": reply_to,
                            "images": images or [],
                        },
                    },
                )
            except Exception:
                # Best effort push, DB insert already committed.
                pass
    
    return {
        "success": True, 
        "id": new_id,
        "timestamp": timestamp.isoformat()
    }
