"""
Games Router - Aviator, Apple Fortune, Mines
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import random
import math
import json
from datetime import datetime

from database import get_db, User, Bet
from routers.auth import get_current_user

router = APIRouter()

# ========================
# UTILITY FUNCTIONS
# ========================

def rng_crash_point() -> float:
    """Aviator crash point hisoblash - RNG asosida"""
    r = random.random()
    if r < 0.01:  # 1% instant crash
        return 1.0
    crash = 0.99 / (1 - r)
    return round(min(crash, 200.0), 2)

def check_forced_lose(user: User) -> bool:
    """Admin tomonidan yutqazdirish foizi tekshirish"""
    if user.lose_percent and user.lose_percent > 0:
        return random.random() * 100 < user.lose_percent
    return False

async def deduct_balance(user: User, amount: float, db: AsyncSession):
    if user.balance_frozen:
        raise HTTPException(status_code=403, detail="Balans muzlatilgan")
    if user.balance < amount:
        raise HTTPException(status_code=400, detail="Balans yetarli emas")
    user.balance -= amount
    user.total_lost += amount
    await db.commit()

async def add_win(user: User, amount: float, db: AsyncSession):
    user.balance += amount
    user.total_won += amount
    await db.commit()

async def save_bet(user_id: int, game: str, amount: float, multiplier: float, 
                    win: float, result: str, data: dict, db: AsyncSession):
    bet = Bet(
        user_id=user_id, game=game, amount=amount,
        multiplier=multiplier, win_amount=win, result=result,
        game_data=json.dumps(data)
    )
    db.add(bet)
    await db.commit()

# ========================
# APPLE OF FORTUNE
# ========================

class AppleStartReq(BaseModel):
    amount: float

class ApplePickReq(BaseModel):
    session_id: str
    position: int  # 0-4 (5 apples per row)
    row: int

# In-memory apple sessions
apple_sessions: dict = {}

APPLE_MULTIPLIERS = [1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]

@router.post("/apple/start")
async def apple_start(req: AppleStartReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.games_banned:
        raise HTTPException(403, "O'yinlarga taqiq qo'yilgan")
    if req.amount <= 0:
        raise HTTPException(400, "Noto'g'ri summa")
    
    await deduct_balance(user, req.amount, db)
    
    # Generate hidden apples for each row
    rows = []
    for i in range(7):
        bad_pos = random.randint(0, 4)
        rows.append(bad_pos)
    
    # Force lose check
    forced_lose = check_forced_lose(user)
    session_id = f"apple_{user.id}_{datetime.utcnow().timestamp()}"
    apple_sessions[session_id] = {
        "user_id": user.id,
        "amount": req.amount,
        "rows": rows,
        "current_row": 0,
        "multiplier": 1.0,
        "forced_lose": forced_lose,
        "force_lose_row": random.randint(0, 3) if forced_lose else None
    }
    
    return {"session_id": session_id, "amount": req.amount, "rows_count": 7}

@router.post("/apple/pick")
async def apple_pick(req: ApplePickReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = apple_sessions.get(req.session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(404, "Sessiya topilmadi")
    
    if req.row != session["current_row"]:
        raise HTTPException(400, "Noto'g'ri qator")
    
    bad_pos = session["rows"][req.row]
    
    # Force lose override
    is_bad = req.position == bad_pos
    if session["forced_lose"] and req.row == session.get("force_lose_row"):
        is_bad = True
        bad_pos = req.position
        session["rows"][req.row] = req.position
    
    if is_bad:
        # RED APPLE - yutqazdi
        del apple_sessions[req.session_id]
        await save_bet(user.id, "apple", session["amount"], 0, 0, "lose", 
                       {"rows_completed": req.row, "bad_pos": bad_pos}, db)
        return {"result": "lose", "bad_position": bad_pos, "reveal": session["rows"][:req.row+1]}
    
    # GREEN APPLE - davom etadi
    next_multiplier = APPLE_MULTIPLIERS[min(req.row, len(APPLE_MULTIPLIERS)-1)]
    session["multiplier"] = next_multiplier
    session["current_row"] = req.row + 1
    
    if req.row >= 6:
        # Final row won
        win_amount = round(session["amount"] * next_multiplier, 2)
        await add_win(user, win_amount, db)
        del apple_sessions[req.session_id]
        await save_bet(user.id, "apple", session["amount"], next_multiplier, win_amount, "win",
                       {"completed": True}, db)
        db_user = await db.get(User, user.id)
        return {"result": "win", "multiplier": next_multiplier, "win_amount": win_amount, 
                "balance": db_user.balance, "final": True}
    
    return {
        "result": "continue",
        "multiplier": next_multiplier,
        "next_row": req.row + 1,
        "current_row": req.row
    }

@router.post("/apple/cashout")
async def apple_cashout(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = apple_sessions.get(session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(404, "Sessiya topilmadi")
    if session["current_row"] == 0:
        raise HTTPException(400, "Birinchi qatordan oldin cashout bo'lmaydi")
    
    win_amount = round(session["amount"] * session["multiplier"], 2)
    await add_win(user, win_amount, db)
    del apple_sessions[session_id]
    await save_bet(user.id, "apple", session["amount"], session["multiplier"], win_amount, "cashout",
                   {"rows_completed": session["current_row"]}, db)
    db_user = await db.get(User, user.id)
    return {"result": "cashout", "multiplier": session["multiplier"], 
            "win_amount": win_amount, "balance": db_user.balance}

# ========================
# MINES
# ========================

class MinesStartReq(BaseModel):
    amount: float
    mines_count: int  # 1-24

class MinesOpenReq(BaseModel):
    session_id: str
    cell: int  # 0-24

mines_sessions: dict = {}

def mines_multiplier(opened: int, mines: int) -> float:
    """Mines koeffitsient hisoblash"""
    safe = 25 - mines
    if opened == 0:
        return 1.0
    mult = 1.0
    for i in range(opened):
        mult *= (25 - mines - i) / (25 - i)
    return round(1 / mult * 0.97, 2)  # 3% house edge

@router.post("/mines/start")
async def mines_start(req: MinesStartReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.games_banned:
        raise HTTPException(403, "O'yinlarga taqiq qo'yilgan")
    if req.mines_count < 1 or req.mines_count > 24:
        raise HTTPException(400, "Mina soni 1-24 oralig'ida bo'lishi kerak")
    if req.amount <= 0:
        raise HTTPException(400, "Noto'g'ri summa")
    
    await deduct_balance(user, req.amount, db)
    
    # Generate mine positions
    all_cells = list(range(25))
    mine_positions = set(random.sample(all_cells, req.mines_count))
    
    forced_lose = check_forced_lose(user)
    session_id = f"mines_{user.id}_{datetime.utcnow().timestamp()}"
    mines_sessions[session_id] = {
        "user_id": user.id,
        "amount": req.amount,
        "mines": mine_positions,
        "mines_count": req.mines_count,
        "opened": [],
        "forced_lose": forced_lose,
        "force_mine": random.choice(list(mine_positions)) if forced_lose else None
    }
    
    return {"session_id": session_id, "mines_count": req.mines_count, "amount": req.amount}

@router.post("/mines/open")
async def mines_open(req: MinesOpenReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = mines_sessions.get(req.session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(404, "Sessiya topilmadi")
    if req.cell in session["opened"]:
        raise HTTPException(400, "Bu katak allaqachon ochilgan")
    if req.cell < 0 or req.cell > 24:
        raise HTTPException(400, "Noto'g'ri katak raqami")
    
    is_mine = req.cell in session["mines"]
    
    # Force lose: if forced and not already forced a mine, make this one a mine
    if session["forced_lose"] and session["force_mine"] and req.cell == session["force_mine"]:
        is_mine = True
    
    if is_mine:
        del mines_sessions[req.session_id]
        await save_bet(user.id, "mines", session["amount"], 0, 0, "lose",
                       {"opened": session["opened"], "mines": list(session["mines"])}, db)
        return {
            "result": "mine",
            "mine_positions": list(session["mines"]),
            "cell": req.cell
        }
    
    session["opened"].append(req.cell)
    opened_count = len(session["opened"])
    current_mult = mines_multiplier(opened_count, session["mines_count"])
    potential_win = round(session["amount"] * current_mult, 2)
    
    # Check if all safe cells opened (win)
    safe_cells = 25 - session["mines_count"]
    if opened_count >= safe_cells:
        await add_win(user, potential_win, db)
        del mines_sessions[req.session_id]
        await save_bet(user.id, "mines", session["amount"], current_mult, potential_win, "win",
                       {"all_opened": True}, db)
        db_user = await db.get(User, user.id)
        return {"result": "win", "multiplier": current_mult, "win_amount": potential_win,
                "balance": db_user.balance, "mine_positions": list(session["mines"])}
    
    return {
        "result": "safe",
        "cell": req.cell,
        "opened": session["opened"],
        "multiplier": current_mult,
        "potential_win": potential_win
    }

@router.post("/mines/cashout")
async def mines_cashout(session_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = mines_sessions.get(session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(404, "Sessiya topilmadi")
    if not session["opened"]:
        raise HTTPException(400, "Hech narsa ochmadingiz")
    
    mult = mines_multiplier(len(session["opened"]), session["mines_count"])
    win_amount = round(session["amount"] * mult, 2)
    await add_win(user, win_amount, db)
    mine_positions = list(session["mines"])
    del mines_sessions[session_id]
    await save_bet(user.id, "mines", session["amount"], mult, win_amount, "cashout",
                   {"opened": session["opened"]}, db)
    db_user = await db.get(User, user.id)
    return {
        "result": "cashout", "multiplier": mult, "win_amount": win_amount,
        "balance": db_user.balance, "mine_positions": mine_positions
    }

# ========================
# AVIATOR
# ========================

class AviatorBetReq(BaseModel):
    amount: float
    auto_cashout: Optional[float] = None  # Auto cashout koeffitsient

aviator_bets: dict = {}  # {user_id: {"amount": x, "auto_cashout": y}}

@router.post("/aviator/bet")
async def aviator_bet(req: AviatorBetReq, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.games_banned:
        raise HTTPException(403, "O'yinlarga taqiq qo'yilgan")
    if req.amount <= 0:
        raise HTTPException(400, "Noto'g'ri summa")
    if user.id in aviator_bets:
        raise HTTPException(400, "Allaqachon tikuvingiz bor")
    
    await deduct_balance(user, req.amount, db)
    aviator_bets[user.id] = {
        "amount": req.amount,
        "auto_cashout": req.auto_cashout,
        "placed_at": datetime.utcnow().isoformat()
    }
    return {"status": "bet_placed", "amount": req.amount}

@router.post("/aviator/cashout")
async def aviator_cashout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Manual cashout - GameManager tomonidan ham chaqiriladi"""
    if user.id not in aviator_bets:
        raise HTTPException(400, "Tikuvingiz yo'q")
    return {"status": "cashout_requested"}

@router.get("/history")
async def bet_history(limit: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Bet).where(Bet.user_id == user.id)
        .order_by(Bet.created_at.desc()).limit(limit)
    )
    bets = result.scalars().all()
    return [{
        "id": b.id, "game": b.game, "amount": b.amount,
        "multiplier": b.multiplier, "win_amount": b.win_amount,
        "result": b.result, "created_at": b.created_at.isoformat()
    } for b in bets]
