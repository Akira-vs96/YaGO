"""Per-user events. A single API worker is required for this in-memory fanout."""
import json
from uuid import UUID

from fastapi import WebSocket
from sqlalchemy import text

from .db import SessionLocal

connections: dict[WebSocket, UUID] = {}


async def publish(event: str, data: dict):
    subscribers = tuple(connections.items())
    if not subscribers:
        return
    recipients = set()
    with SessionLocal() as db:
        if event == "driverMoved":
            rows = db.execute(text("""SELECT o.customer_id,p.user_id FROM orders o
                JOIN performers p ON p.id=o.performer_id
                WHERE p.id=:id AND o.status_code NOT IN ('completed','cancelled')"""), {"id": data["id"]})
            for row in rows:
                recipients.update((str(row.customer_id), str(row.user_id)))
            if not recipients:
                return
        else:
            recipients.add(data["customerId"])
            if data.get("performerId"):
                performer_user = db.execute(text("SELECT user_id FROM performers WHERE id=:id"),
                    {"id": data["performerId"]}).scalar()
                if performer_user:
                    recipients.add(str(performer_user))
        allowed_sessions = set(db.execute(text("""SELECT s.id FROM sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.id=ANY(CAST(:sessions AS uuid[]))
              AND s.revoked_at IS NULL AND s.expires_at>now() AND u.is_active
              AND (s.user_id=ANY(CAST(:recipients AS uuid[])) OR EXISTS (
                  SELECT 1 FROM user_roles r
                  WHERE r.user_id=s.user_id AND r.role_code IN ('operator','admin')
              ))"""), {"sessions": [session for _, session in subscribers],
                         "recipients": list(recipients)}).scalars())
    message = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    for websocket, session in subscribers:
        if session in allowed_sessions:
            try:
                await websocket.send_text(message)
            except Exception:
                connections.pop(websocket, None)
