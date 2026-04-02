"""
Database - Railway PostgreSQL bilan ishlash uchun sozlangan
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, BigInteger
from datetime import datetime
from typing import Optional
import os

_db_url = os.environ.get("DATABASE_URL", "postgresql://casino:casino123@localhost/casinodb")

if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql://") and "+asyncpg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

DATABASE_URL = _db_url
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    login: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    total_won: Mapped[float] = mapped_column(Float, default=0.0)
    total_lost: Mapped[float] = mapped_column(Float, default=0.0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    balance_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    games_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    lose_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    bets: Mapped[list["Bet"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")

class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    game: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    multiplier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    result: Mapped[str] = mapped_column(String(16))
    game_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["User"] = relationship(back_populates="bets")

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    admin_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user: Mapped["User"] = relationship(back_populates="transactions")

class Promo(Base):
    __tablename__ = "promos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    bonus_percent: Mapped[float] = mapped_column(Float)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    require_channel: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PromoUse(Base):
    __tablename__ = "promo_uses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promos.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AdminConfig(Base):
    __tablename__ = "admin_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[str] = mapped_column(Text)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
