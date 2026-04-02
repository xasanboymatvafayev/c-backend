"""
Promo Router
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from database import get_db, User, Promo, PromoUse
from routers.auth import get_current_user

router = APIRouter()

class ApplyPromoReq(BaseModel):
    code: str
    deposit_amount: float

@router.post("/apply")
async def apply_promo(req: ApplyPromoReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Promo).where(Promo.code == req.code.upper(), Promo.is_active == True))
    promo = result.scalar_one_or_none()
    
    if not promo:
        raise HTTPException(404, "Promokod topilmadi yoki faol emas")
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        raise HTTPException(400, "Promokod muddati o'tgan")
    if promo.max_uses and promo.used_count >= promo.max_uses:
        raise HTTPException(400, "Promokod chegarasiga yetildi")
    
    # Bir marta ishlatish tekshirish
    used = await db.execute(
        select(PromoUse).where(PromoUse.promo_id == promo.id, PromoUse.user_id == user.id)
    )
    if used.scalar_one_or_none():
        raise HTTPException(400, "Siz bu promokodni allaqachon ishlatgansiz")
    
    bonus = req.deposit_amount * promo.bonus_percent / 100
    user.balance += bonus
    promo.used_count += 1
    
    use = PromoUse(promo_id=promo.id, user_id=user.id)
    db.add(use)
    await db.commit()
    
    return {"status": "applied", "bonus": round(bonus, 2), "new_balance": round(user.balance, 2)}
