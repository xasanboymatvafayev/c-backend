"""
Admin Register Router - Bot tomonidan foydalanuvchi yaratish uchun
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import os

from database import get_db, User

router = APIRouter()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin_super_secret_token")

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Admin token noto'g'ri")

class RegisterReq(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    login: str
    password_hash: str

@router.post("/register")
async def register_user(req: RegisterReq, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    # Mavjud foydalanuvchini tekshirish
    existing = await db.execute(select(User).where(User.telegram_id == req.telegram_id))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Bu Telegram ID allaqachon ro'yxatdan o'tgan")
    
    user = User(
        telegram_id=req.telegram_id,
        username=req.username,
        login=req.login,
        password_hash=req.password_hash,
        balance=0.0
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return {"id": user.id, "login": user.login, "balance": user.balance}

@router.get("/user_by_tg/{telegram_id}")
async def get_user_by_tg(telegram_id: int, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Topilmadi")
    return {
        "id": user.id, "login": user.login, "username": user.username,
        "balance": user.balance, "total_won": user.total_won, "total_lost": user.total_lost,
        "is_blocked": user.is_blocked, "created_at": user.created_at.isoformat()
    }
