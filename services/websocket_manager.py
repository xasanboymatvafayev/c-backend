"""
WebSocket Manager - Ulanishlarni boshqarish
"""
from fastapi import WebSocket
import json
from typing import Dict

class WebSocketManager:
    def __init__(self):
        self.active: Dict[int, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active[user_id] = websocket
    
    def disconnect(self, user_id: int):
        self.active.pop(user_id, None)
    
    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        for uid, ws in self.active.items():
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect(uid)
    
    async def send_personal(self, data: dict, user_id: int):
        ws = self.active.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                self.disconnect(user_id)
