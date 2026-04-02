"""
Admin Router - Panel boshqaruvi
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import os

from database import get_db, User, Bet, Transaction, Promo

router = APIRouter()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin_super_secret_token")

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Admin token noto'g'ri")

# ========================
# STATISTIKA
# ========================

@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    total_users = await db.scalar(select(func.count(User.id)))
    total_balance = await db.scalar(select(func.sum(User.balance))) or 0
    total_won = await db.scalar(select(func.sum(User.total_won))) or 0
    total_lost = await db.scalar(select(func.sum(User.total_lost))) or 0
    
    # Bugungi statistika
    today = date.today()
    today_bets = await db.scalar(
        select(func.count(Bet.id)).where(func.date(Bet.created_at) == today)
    ) or 0
    today_volume = await db.scalar(
        select(func.sum(Bet.amount)).where(func.date(Bet.created_at) == today)
    ) or 0
    
    return {
        "total_users": total_users,
        "total_balance": round(total_balance, 2),
        "total_won": round(total_won, 2),
        "total_lost": round(total_lost, 2),
        "house_profit": round(total_lost - total_won, 2),
        "today_bets": today_bets,
        "today_volume": round(today_volume, 2)
    }

@router.get("/top_winners")
async def top_winners(limit: int = 10, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(
        select(User).order_by(desc(User.total_won)).limit(limit)
    )
    users = result.scalars().all()
    return [{"id": u.id, "login": u.login, "username": u.username,
             "total_won": u.total_won, "balance": u.balance} for u in users]

@router.get("/top_losers")
async def top_losers(limit: int = 10, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(
        select(User).order_by(desc(User.total_lost)).limit(limit)
    )
    users = result.scalars().all()
    return [{"id": u.id, "login": u.login, "username": u.username,
             "total_lost": u.total_lost, "balance": u.balance} for u in users]

@router.get("/users")
async def list_users(limit: int = 50, offset: int = 0, 
                      db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(
        select(User).order_by(desc(User.created_at)).limit(limit).offset(offset)
    )
    users = result.scalars().all()
    return [{
        "id": u.id, "telegram_id": u.telegram_id, "login": u.login,
        "username": u.username, "balance": u.balance, "total_won": u.total_won,
        "total_lost": u.total_lost, "is_blocked": u.is_blocked,
        "balance_frozen": u.balance_frozen, "games_banned": u.games_banned,
        "lose_percent": u.lose_percent, "created_at": u.created_at.isoformat()
    } for u in users]

# ========================
# FOYDALANUVCHI NAZORAT
# ========================

class UserControlReq(BaseModel):
    user_id: int
    action: str  # block, unblock, freeze, unfreeze, ban_games, unban_games
    lose_percent: Optional[float] = None

@router.post("/user/control")
async def user_control(req: UserControlReq, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    
    if req.action == "block":
        user.is_blocked = True
    elif req.action == "unblock":
        user.is_blocked = False
    elif req.action == "freeze":
        user.balance_frozen = True
    elif req.action == "unfreeze":
        user.balance_frozen = False
    elif req.action == "ban_games":
        user.games_banned = True
    elif req.action == "unban_games":
        user.games_banned = False
    elif req.action == "set_lose_percent":
        user.lose_percent = req.lose_percent
    elif req.action == "remove_lose_percent":
        user.lose_percent = None
    else:
        raise HTTPException(400, "Noto'g'ri action")
    
    await db.commit()
    return {"status": "ok", "action": req.action, "user_id": req.user_id}

class BalanceAdjustReq(BaseModel):
    user_id: int
    amount: float
    note: Optional[str] = None

@router.post("/user/add_balance")
async def add_balance(req: BalanceAdjustReq, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    user.balance += req.amount
    
    tx = Transaction(
        user_id=req.user_id, type="deposit", amount=req.amount,
        status="confirmed", admin_confirmed=True, note=req.note,
        confirmed_at=datetime.utcnow()
    )
    db.add(tx)
    await db.commit()
    return {"status": "ok", "new_balance": user.balance}

# ========================
# TO'LOV TASDIQLASH
# ========================

@router.get("/pending_deposits")
async def pending_deposits(db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(
        select(Transaction, User).join(User).where(
            Transaction.type == "deposit",
            Transaction.status == "pending"
        ).order_by(desc(Transaction.created_at))
    )
    rows = result.all()
    return [{
        "tx_id": tx.id, "user_id": user.id, "login": user.login,
        "username": user.username, "amount": tx.amount,
        "order_id": tx.order_id, "created_at": tx.created_at.isoformat()
    } for tx, user in rows]

class ConfirmDepositReq(BaseModel):
    tx_id: int

@router.post("/confirm_deposit")
async def confirm_deposit(req: ConfirmDepositReq, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    tx = await db.get(Transaction, req.tx_id)
    if not tx:
        raise HTTPException(404, "Tranzaksiya topilmadi")
    if tx.status != "pending":
        raise HTTPException(400, "Tranzaksiya allaqachon ko'rib chiqilgan")
    
    user = await db.get(User, tx.user_id)
    user.balance += tx.amount
    tx.status = "confirmed"
    tx.admin_confirmed = True
    tx.confirmed_at = datetime.utcnow()
    await db.commit()
    return {"status": "confirmed", "user_balance": user.balance}

# ========================
# PROMOKOD
# ========================

class CreatePromoReq(BaseModel):
    code: str
    bonus_percent: float
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    require_channel: Optional[str] = None

@router.post("/promo/create")
async def create_promo(req: CreatePromoReq, db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    promo = Promo(
        code=req.code.upper(),
        bonus_percent=req.bonus_percent,
        max_uses=req.max_uses,
        expires_at=req.expires_at,
        require_channel=req.require_channel
    )
    db.add(promo)
    await db.commit()
    return {"status": "created", "code": promo.code}

@router.get("/promos")
async def list_promos(db: AsyncSession = Depends(get_db), _=Depends(verify_admin)):
    result = await db.execute(select(Promo).order_by(desc(Promo.created_at)))
    promos = result.scalars().all()
    return [{
        "id": p.id, "code": p.code, "bonus_percent": p.bonus_percent,
        "max_uses": p.max_uses, "used_count": p.used_count,
        "is_active": p.is_active, "expires_at": p.expires_at.isoformat() if p.expires_at else None
    } for p in promos]
