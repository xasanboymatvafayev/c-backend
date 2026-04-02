"""
Game Manager - Aviator real-time loop
WebSocket orqali barcha foydalanuvchilarga broadcast
"""
import asyncio
import random
import math
import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.websocket_manager import WebSocketManager

class GameManager:
    def __init__(self, ws_manager):
        self.ws_manager = ws_manager
        self.current_multiplier = 1.0
        self.crash_point = 1.0
        self.phase = "waiting"  # waiting, flying, crashed
        self.bets = {}  # {user_id: {amount, auto_cashout, db, user}}
        self.round_id = 0
        self.history = []  # son 20 ta crash point
    
    def generate_crash_point(self) -> float:
        r = random.random()
        if r < 0.03:
            return round(random.uniform(1.0, 1.5), 2)
        crash = 0.99 / (1 - r)
        return round(min(crash, 200.0), 2)
    
    async def run_aviator_loop(self):
        """Cheksiz Aviator o'yin sikli"""
        while True:
            await self.waiting_phase()
            await self.flying_phase()
            await self.crashed_phase()
    
    async def waiting_phase(self):
        """Kutish bosqichi - 5 sekund"""
        self.phase = "waiting"
        self.round_id += 1
        self.crash_point = self.generate_crash_point()
        self.current_multiplier = 1.0
        self.bets = {}
        
        await self.ws_manager.broadcast({
            "type": "aviator_waiting",
            "round_id": self.round_id,
            "countdown": 5,
            "history": self.history[-10:]
        })
        
        for i in range(5, 0, -1):
            await self.ws_manager.broadcast({
                "type": "aviator_countdown",
                "countdown": i
            })
            await asyncio.sleep(1)
    
    async def flying_phase(self):
        """Uchish bosqichi"""
        self.phase = "flying"
        start_time = asyncio.get_event_loop().time()
        
        await self.ws_manager.broadcast({
            "type": "aviator_start",
            "round_id": self.round_id
        })
        
        tick_rate = 0.1  # 100ms
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            # Exponential growth: koeffitsient tez oshadi
            self.current_multiplier = round(math.exp(elapsed * 0.06), 2)
            
            if self.current_multiplier >= self.crash_point:
                self.current_multiplier = self.crash_point
                break
            
            # Auto cashout tekshirish
            auto_cashouts = []
            for uid, bet in list(self.bets.items()):
                if bet.get("auto_cashout") and self.current_multiplier >= bet["auto_cashout"]:
                    auto_cashouts.append(uid)
            
            for uid in auto_cashouts:
                await self.process_cashout(uid, self.current_multiplier)
            
            await self.ws_manager.broadcast({
                "type": "aviator_tick",
                "multiplier": self.current_multiplier,
                "round_id": self.round_id
            })
            
            await asyncio.sleep(tick_rate)
    
    async def crashed_phase(self):
        """Crash bosqichi"""
        self.phase = "crashed"
        
        # Qolgan barcha tikuvlarni yutqazdirish
        for uid in list(self.bets.keys()):
            bet = self.bets[uid]
            if "db" in bet and "user" in bet:
                await self.process_lose(uid)
        
        self.history.append(self.crash_point)
        if len(self.history) > 50:
            self.history = self.history[-50:]
        
        await self.ws_manager.broadcast({
            "type": "aviator_crashed",
            "crash_point": self.crash_point,
            "round_id": self.round_id
        })
        
        await asyncio.sleep(2)
    
    async def process_cashout(self, user_id: int, multiplier: float):
        """Cashout qayta ishlash"""
        bet = self.bets.pop(user_id, None)
        if not bet:
            return
        
        win_amount = round(bet["amount"] * multiplier, 2)
        
        # DB update - async orqali
        if "db" in bet and "user_obj" in bet:
            user = bet["user_obj"]
            user.balance += win_amount
            user.total_won += win_amount
            await bet["db"].commit()
        
        await self.ws_manager.send_personal({
            "type": "aviator_cashout",
            "multiplier": multiplier,
            "win_amount": win_amount,
            "user_id": user_id
        }, user_id)
    
    async def process_lose(self, user_id: int):
        """Yutqazdi"""
        self.bets.pop(user_id, None)
        await self.ws_manager.send_personal({
            "type": "aviator_lose",
            "crash_point": self.crash_point,
            "user_id": user_id
        }, user_id)
    
    async def handle_message(self, user_id: int, msg: dict, websocket):
        """WebSocket xabarlarni qayta ishlash"""
        msg_type = msg.get("type")
        
        if msg_type == "aviator_bet":
            if self.phase != "waiting":
                await websocket.send_text(json.dumps({
                    "type": "error", "message": "Hozir tikish mumkin emas"
                }))
                return
            
            amount = msg.get("amount", 0)
            auto_cashout = msg.get("auto_cashout")
            
            self.bets[user_id] = {
                "amount": amount,
                "auto_cashout": auto_cashout,
                "placed_at": datetime.utcnow().isoformat()
            }
            
            await websocket.send_text(json.dumps({
                "type": "bet_confirmed",
                "amount": amount
            }))
        
        elif msg_type == "aviator_cashout":
            if self.phase != "flying" or user_id not in self.bets:
                await websocket.send_text(json.dumps({
                    "type": "error", "message": "Cashout mumkin emas"
                }))
                return
            await self.process_cashout(user_id, self.current_multiplier)
        
        elif msg_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
        
        elif msg_type == "get_state":
            await websocket.send_text(json.dumps({
                "type": "state",
                "phase": self.phase,
                "multiplier": self.current_multiplier,
                "round_id": self.round_id,
                "history": self.history[-10:]
            }))
