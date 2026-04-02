"""
Auth Router - Login, token yaratish
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt
import bcrypt
import os

from database import get_db, User

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "casino_secret_key_change_in_prod")
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    balance: float

def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Token noto'g'ri")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Akkaunt bloklangan")
    return user

@router.post("/token", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == form.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Login yoki parol noto'g'ri")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Akkaunt bloklangan")
    
    user.last_active = datetime.utcnow()
    await db.commit()
    
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id,
        balance=user.balance
    )

class LoginRequest(BaseModel):
    login: str
    password: str

@router.post("/login")
async def login_json(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == req.login))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Login yoki parol noto'g'ri")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Akkaunt bloklangan")
    
    user.last_active = datetime.utcnow()
    await db.commit()
    
    return {
        "access_token": create_token(user.id),
        "token_type": "bearer",
        "user_id": user.id,
        "balance": user.balance,
        "username": user.username or user.login
    }
