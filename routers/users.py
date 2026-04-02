"""
Users Router
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db, User
from routers.auth import get_current_user

router = APIRouter()

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "login": user.login,
        "username": user.username,
        "balance": user.balance,
        "total_won": user.total_won,
        "total_lost": user.total_lost,
        "created_at": user.created_at.isoformat()
    }

@router.get("/balance")
async def get_balance(user: User = Depends(get_current_user)):
    return {"balance": user.balance}
