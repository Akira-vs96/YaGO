"""Per-user events. A single API worker is required for this in-memory fanout."""
import json

from fastapi import WebSocket
from sqlalchemy import text

from .db import SessionLocal

connections: dict[WebSocket, dict] = {}


async def publish(event: str, data: dict):
    recipients = set()
    if event == "driverMoved":
        with SessionLocal() as db:
            rows = db.execute(text("""SELECT o.customer_id,p.user_id FROM orders o
                JOIN performers p ON p.id=o.performer_id
                WHERE p.id=:id AND o.status_code NOT IN ('completed','cancelled')"""), {"id": data["id"]})
            for row in rows:
                recipients.update((str(row.customer_id), str(row.user_id)))
    else:
        recipients.add(data["customerId"])
        if data.get("performerId"):
            with SessionLocal() as db:
                performer_user = db.execute(text("SELECT user_id FROM performers WHERE id=:id"),
                    {"id": data["performerId"]}).scalar()
                if performer_user:
                    recipients.add(str(performer_user))
    message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    for websocket, user in tuple(connections.items()):
        if user["id"] in recipients or {"operator", "admin"} & set(user["roles"]):
            try:
                await websocket.send_text(message)
            except Exception:
                connections.pop(websocket, None)
