"""
Payments Router - CheckCard.uz integratsiyasi
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import httpx
import os
from datetime import datetime

from database import get_db, User, Transaction
from routers.auth import get_current_user

router = APIRouter()

CHECKCARD_BASE = "https://checkcard.uz/api"
SHOP_ID = os.getenv("CHECKCARD_SHOP_ID", "YOUR_SHOP_ID")
SHOP_KEY = os.getenv("CHECKCARD_SHOP_KEY", "YOUR_SHOP_KEY")

class DepositReq(BaseModel):
    amount: float  # so'mda

class WithdrawReq(BaseModel):
    amount: float
    card_number: Optional[str] = None
    note: Optional[str] = None

@router.post("/deposit/create")
async def create_deposit(req: DepositReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if req.amount < 1000:
        raise HTTPException(400, "Minimum to'lov 1000 so'm")
    if user.balance_frozen:
        raise HTTPException(403, "Balans muzlatilgan")
    
    # CheckCard orqali to'lov yaratish
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CHECKCARD_BASE}", params={
                "method": "create",
                "shop_id": SHOP_ID,
                "shop_key": SHOP_KEY,
                "amount": int(req.amount)
            })
            data = resp.json()
    except Exception as e:
        raise HTTPException(503, f"To'lov tizimi xatosi: {str(e)}")
    
    if data.get("status") != "success":
        raise HTTPException(400, data.get("message", "To'lov yaratib bo'lmadi"))
    
    order_id = data["order"]
    
    # Tranzaksiya saqlash
    tx = Transaction(
        user_id=user.id,
        type="deposit",
        amount=req.amount,
        status="pending",
        order_id=order_id
    )
    db.add(tx)
    await db.commit()
    
    return {
        "status": "created",
        "order_id": order_id,
        "amount": req.amount,
        "tx_id": tx.id,
        "message": "Admin tasdiqlashini kuting"
    }

@router.get("/deposit/check/{order_id}")
async def check_deposit(order_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CHECKCARD_BASE}", params={
                "method": "check",
                "order": order_id
            })
            data = resp.json()
    except Exception:
        raise HTTPException(503, "To'lov tizimi bilan bog'lanib bo'lmadi")
    
    # DB dan tranzaksiyani topish
    result = await db.execute(
        select(Transaction).where(
            Transaction.order_id == order_id,
            Transaction.user_id == user.id
        )
    )
    tx = result.scalar_one_or_none()
    
    return {
        "order_status": data.get("data", {}).get("status"),
        "tx_status": tx.status if tx else None,
        "amount": tx.amount if tx else None
    }

@router.post("/withdraw/request")
async def withdraw_request(req: WithdrawReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.balance_frozen:
        raise HTTPException(403, "Balans muzlatilgan")
    if req.amount <= 0:
        raise HTTPException(400, "Noto'g'ri summa")
    if user.balance < req.amount:
        raise HTTPException(400, "Balans yetarli emas")
    
    # Balansni ushlab turish
    user.balance -= req.amount
    
    tx = Transaction(
        user_id=user.id,
        type="withdraw",
        amount=req.amount,
        status="pending",
        note=req.note or req.card_number
    )
    db.add(tx)
    await db.commit()
    
    return {
        "status": "pending",
        "message": "Yechish so'rovi admin ko'rib chiqadi",
        "amount": req.amount,
        "tx_id": tx.id,
        "new_balance": user.balance
    }

@router.get("/history")
async def payment_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc()).limit(20)
    )
    txs = result.scalars().all()
    return [{
        "id": t.id, "type": t.type, "amount": t.amount,
        "status": t.status, "created_at": t.created_at.isoformat(),
        "confirmed_at": t.confirmed_at.isoformat() if t.confirmed_at else None
    } for t in txs]
