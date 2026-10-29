"""YaGo HTTP and WebSocket entrypoint."""
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from . import auth, events, maps, services  # noqa: E402
from .db import SessionLocal, engine, migrate  # noqa: E402


@asynccontextmanager
async def lifespan(_):
    migrate()
    yield
    engine.dispose()


app = FastAPI(title="YaGo API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])
app.include_router(auth.router)
app.include_router(services.router)
app.include_router(maps.router)


@app.get("/api/health", tags=["health"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"ok": True, "db": "connected"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    with SessionLocal() as db:
        identity = auth.session_user(db, websocket.cookies.get("yago_session"))
        user = auth.public_user(db, str(identity["user_id"])) if identity else None
    if not user:
        await websocket.close(code=4401)
        return
    origin = websocket.headers.get("origin")
    allowed = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
    if origin and origin not in allowed:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    events.connections[websocket] = user
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                with SessionLocal() as db:
                    if not auth.session_user(db, websocket.cookies.get("yago_session")):
                        await websocket.close(code=4401)
                        break
    except WebSocketDisconnect:
        pass
    finally:
        events.connections.pop(websocket, None)
