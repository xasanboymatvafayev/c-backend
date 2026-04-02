"""
Casino Platform - FastAPI Backend (to'liq versiya)
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import json
from contextlib import asynccontextmanager

from routers import auth, users, games, admin, payments, promo, register
from services.game_manager import GameManager
from services.websocket_manager import WebSocketManager
from database import init_db

ws_manager = WebSocketManager()
game_manager = GameManager(ws_manager)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(game_manager.run_aviator_loop())
    yield

app = FastAPI(title="Casino API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(promo.router, prefix="/api/promo", tags=["promo"])
app.include_router(register.router, prefix="/api/auth", tags=["register"])

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await game_manager.handle_message(user_id, msg, websocket)
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)
    except Exception:
        ws_manager.disconnect(user_id)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
