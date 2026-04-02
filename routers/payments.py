"""
Payments Router - CheckCard.uz integratsiyasi (YANGILANGAN)
- /deposit/create  → payurl=true bilan to'lov sahifasi qaytaradi
- /deposit/check   → status tekshirish + avtomatik balans qo'shish
- /withdraw/request → karta bilan yechish so'rovi
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
SHOP_ID  = os.getenv("CHECKCARD_SHOP_ID", "")
SHOP_KEY = os.getenv("CHECKCARD_SHOP_KEY", "")

class DepositReq(BaseModel):
    amount: float

class WithdrawReq(BaseModel):
    amount: float
    card_number: Optional[str] = None
    note: Optional[str] = None

# ── TO'LDIRISH YARATISH ───────────────────────────────────────────────
@router.post("/deposit/create")
async def create_deposit(
    req: DepositReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if req.amount < 1000:
        raise HTTPException(400, "Minimum to'lov 1000 so'm")
    if user.balance_frozen:
        raise HTTPException(403, "Balans muzlatilgan")

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(CHECKCARD_BASE, params={
                "method":   "create",
                "shop_id":  SHOP_ID,
                "shop_key": SHOP_KEY,
                "amount":   int(req.amount),
                "payurl":   "true"          # ← to'lov sahifasi havolasi
            })
            data = r.json()
    except Exception as e:
        raise HTTPException(503, f"To'lov tizimi xatosi: {e}")

    if data.get("status") != "success":
        msg = data.get("message","")
        if "pending" in msg.lower():
            raise HTTPException(400, f"Bu miqdorda kutilayotgan to'lov bor. {int(req.amount)+500:,} so'm kiriting")
        raise HTTPException(400, msg or "To'lov yaratib bo'lmadi")

    order_id = data["order"]
    pay_url  = data.get("payurl","")
    card     = data.get("card","")

    # Tranzaksiya saqlash
    tx = Transaction(
        user_id=user.id, type="deposit", amount=req.amount,
        status="pending", order_id=order_id
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)

    return {
        "status":   "created",
        "order_id": order_id,
        "pay_url":  pay_url,       # ← web app shu URL ga yo'naltiradi
        "card":     card,
        "amount":   req.amount,
        "tx_id":    tx.id
    }

# ── TO'LOV STATUSINI TEKSHIRISH ───────────────────────────────────────
@router.get("/deposit/check/{order_id}")
async def check_deposit(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r    = await c.get(CHECKCARD_BASE, params={"method": "check", "order": order_id})
            data = r.json()
    except Exception:
        raise HTTPException(503, "To'lov tizimi bilan bog'lanib bo'lmadi")

    cc_status = data.get("data",{}).get("status","")
    cc_amount = data.get("data",{}).get("amount", 0)

    # DB tranzaksiyani topish
    res = await db.execute(
        select(Transaction).where(
            Transaction.order_id == order_id,
            Transaction.user_id  == user.id
        )
    )
    tx = res.scalar_one_or_none()

    # Agar "paid" bo'lsa va hali tasdiqlanmagan bo'lsa — avtomatik balans qo'shish
    if cc_status == "paid" and tx and tx.status == "pending":
        user.balance     += tx.amount
        tx.status         = "confirmed"
        tx.admin_confirmed = True
        tx.confirmed_at   = datetime.utcnow()
        await db.commit()

    return {
        "cc_status": cc_status,
        "tx_status": tx.status if tx else None,
        "amount":    tx.amount if tx else cc_amount,
        "confirmed": tx.status == "confirmed" if tx else False
    }

# ── TO'LOV BEKOR QILISH ───────────────────────────────────────────────
@router.post("/deposit/cancel/{order_id}")
async def cancel_deposit(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(Transaction).where(
            Transaction.order_id == order_id,
            Transaction.user_id  == user.id
        )
    )
    tx = res.scalar_one_or_none()
    if tx and tx.status == "paid":
        raise HTTPException(400, "To'lov allaqachon qabul qilingan!")

    if tx:
        tx.status = "cancel"
        await db.commit()

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.get(CHECKCARD_BASE, params={"method": "cancel", "order": order_id})
    except Exception:
        pass

    return {"status": "cancelled"}

# ── YECHISH SO'ROVI ───────────────────────────────────────────────────
@router.post("/withdraw/request")
async def withdraw_request(
    req: WithdrawReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user.balance_frozen:
        raise HTTPException(403, "Balans muzlatilgan")
    if req.amount <= 0:
        raise HTTPException(400, "Noto'g'ri summa")
    if req.amount < 10000:
        raise HTTPException(400, "Minimum yechish 10,000 so'm")
    if user.balance < req.amount:
        raise HTTPException(400, f"Balans yetarli emas. Mavjud: {user.balance:,.0f} so'm")

    user.balance -= req.amount
    tx = Transaction(
        user_id=user.id, type="withdraw", amount=req.amount,
        status="pending", note=req.note or req.card_number
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)

    return {
        "status":      "pending",
        "message":     "So'rov admin ko'rib chiqadi",
        "amount":      req.amount,
        "tx_id":       tx.id,
        "new_balance": user.balance
    }

# ── TARIX ─────────────────────────────────────────────────────────────
@router.get("/history")
async def payment_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc()).limit(30)
    )
    txs = res.scalars().all()
    return [{
        "id":           t.id,
        "type":         t.type,
        "amount":       t.amount,
        "status":       t.status,
        "order_id":     t.order_id,
        "note":         t.note,
        "created_at":   t.created_at.isoformat(),
        "confirmed_at": t.confirmed_at.isoformat() if t.confirmed_at else None
    } for t in txs]
