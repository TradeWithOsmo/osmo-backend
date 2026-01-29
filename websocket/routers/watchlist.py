from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from database.connection import get_db
from database.models import Watchlist
from pydantic import BaseModel

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

class WatchlistItem(BaseModel):
    symbol: str
    source: Optional[str] = None
    wallet_address: Optional[str] = None

class WatchlistResponse(BaseModel):
    symbol: str
    source: Optional[str]
    wallet_address: Optional[str]

@router.get("/", response_model=List[WatchlistResponse])
async def get_watchlist(wallet_address: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Watchlist)
    if wallet_address:
        query = query.where(Watchlist.wallet_address == wallet_address)
    
    result = await db.execute(query)
    items = result.scalars().all()
    return items

@router.post("/toggle")
async def toggle_watchlist(item: WatchlistItem, db: AsyncSession = Depends(get_db)):
    # Check if exists
    query = select(Watchlist).where(Watchlist.symbol == item.symbol)
    if item.wallet_address:
        query = query.where(Watchlist.wallet_address == item.wallet_address)
    
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    
    if existing:
        await db.delete(existing)
        await db.commit()
        return {"status": "removed", "symbol": item.symbol}
    else:
        new_item = Watchlist(
            symbol=item.symbol,
            source=item.source,
            wallet_address=item.wallet_address
        )
        db.add(new_item)
        await db.commit()
        return {"status": "added", "symbol": item.symbol}

@router.delete("/{symbol}")
async def remove_from_watchlist(symbol: str, wallet_address: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(Watchlist).where(Watchlist.symbol == symbol)
    if wallet_address:
        query = query.where(Watchlist.wallet_address == wallet_address)
        
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if item:
        await db.delete(item)
        await db.commit()
        return {"status": "success"}
    
    raise HTTPException(status_code=404, detail="Item not found in watchlist")
