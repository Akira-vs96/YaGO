"""Transactional business workflows for the three active services."""
import hashlib
import json
import os
import asyncio
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import User, require
from .db import get_db, row_dict
from .events import publish

router = APIRouter(prefix="/api", tags=["services"])
DB = Annotated[Session, Depends(get_db)]
MONEY = Decimal("0.01")
ROUTE_CACHE = {}


def one(db, sql, **params):
    return row_dict(db.execute(text(sql), params).first())


def many(db, sql, **params):
    return [row_dict(r) for r in db.execute(text(sql), params)]


def amount(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def audit(db, actor, action, subject_type=None, subject_id=None):
    db.execute(text("INSERT INTO audit_events(actor_id,action,subject_type,subject_id) VALUES (:actor,:action,:kind,:id)"),
        {"actor": actor, "action": action, "kind": subject_type, "id": str(subject_id) if subject_id else None})


def active_tariff(db, service):
    tariff = one(db, """SELECT * FROM tariffs WHERE service_type_code=:service AND valid_from<=now()
        AND (valid_to IS NULL OR valid_to>now()) ORDER BY valid_from DESC,id DESC LIMIT 1""", service=service)
    if not tariff:
        raise HTTPException(503, "Действующий тариф не найден")
    return tariff


def order_view(db, order_id):
    order = one(db, """SELECT o.*,p.address_text pickup,p.lat pickup_lat,p.lng pickup_lng,
        d.address_text dropoff,d.lat dropoff_lat,d.lng dropoff_lng,
        r.name restaurant_name, u.full_name customer_name,
        pa.lat performer_lat,pa.lng performer_lng
        FROM orders o JOIN addresses p ON p.id=o.pickup_address_id
        JOIN addresses d ON d.id=o.dropoff_address_id
        LEFT JOIN restaurants r ON r.id=o.restaurant_id JOIN users u ON u.id=o.customer_id
        LEFT JOIN performers pf ON pf.id=o.performer_id
        LEFT JOIN addresses pa ON pa.id=pf.address_id
        WHERE o.id=:id""", id=order_id)
    if not order:
        raise HTTPException(404, "Заказ не найден")
    return {
        "id": str(order["id"]), "type": order["service_type_code"], "status": order["status_code"],
        "customerId": str(order["customer_id"]), "customer": order["customer_name"],
        "performerId": str(order["performer_id"]) if order["performer_id"] else None,
        "performerPosition": {"lat": float(order["performer_lat"]), "lng": float(order["performer_lng"])}
            if order["performer_lat"] is not None and order["status_code"] not in {"completed", "cancelled"} else None,
        "restaurantId": str(order["restaurant_id"]) if order["restaurant_id"] else None,
        "restaurant": order["restaurant_name_snapshot"] or order["restaurant_name"],
        "total": str(order["total_amount"] or 0),
        "discount": str(order["discount_amount"]),
        "delivery": str(order["delivery_amount"]) if order["delivery_amount"] is not None else None,
        "distanceMeters": order["distance_meters"], "durationSeconds": order["duration_seconds"],
        "routeGeometry": order["route_geometry"],
        "start": {"address": order["pickup_snapshot"] or order["pickup"],
                  "lat": float(order["pickup_lat_snapshot"] if order["pickup_lat_snapshot"] is not None else order["pickup_lat"]),
                  "lng": float(order["pickup_lng_snapshot"] if order["pickup_lng_snapshot"] is not None else order["pickup_lng"])},
        "end": {"address": order["dropoff_snapshot"] or order["dropoff"],
                "lat": float(order["dropoff_lat_snapshot"] if order["dropoff_lat_snapshot"] is not None else order["dropoff_lat"]),
                "lng": float(order["dropoff_lng_snapshot"] if order["dropoff_lng_snapshot"] is not None else order["dropoff_lng"])},
        "createdAt": order["created_at"],
        "items": [{"name": r["item_name_snapshot"], "quantity": r["quantity"], "unitPrice": str(r["unit_price"])}
                  for r in many(db, "SELECT item_name_snapshot,quantity,unit_price FROM order_items WHERE order_id=:id ORDER BY id", id=order_id)],
    }


class Point(BaseModel):
    address: str = Field(min_length=2, max_length=500)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Line(BaseModel):
    menuItemId: str
    quantity: int = Field(ge=1, le=99)


class QuoteInput(BaseModel):
    type: Literal["taxi", "food"]
    start: Point | None = None
    end: Point
    restaurantId: str | None = None
    items: list[Line] = Field(default_factory=list, max_length=50)


class CreateOrder(QuoteInput):
    quotedTotal: Decimal = Field(ge=0)
    tariffId: str


async def driving_route(start: Point, end: Point):
    base = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
    url = f"{base}/route/v1/driving/{start.lng},{start.lat};{end.lng},{end.lat}"
    key = (round(start.lat, 5), round(start.lng, 5), round(end.lat, 5), round(end.lng, 5))
    cached = ROUTE_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                response = await client.get(url, params={"overview": "full", "geometries": "geojson"})
                response.raise_for_status()
                data = response.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            if attempt:
                raise HTTPException(503, "Маршрутизация временно недоступна") from exc
            await asyncio.sleep(0.3)
    route = next(iter(data.get("routes", [])), None)
    if not route:
        raise HTTPException(422, "Маршрут между точками не найден")
    if len(ROUTE_CACHE) > 256:
        ROUTE_CACHE.clear()
    ROUTE_CACHE[key] = (time.monotonic(), route)
    return route


def student_discount(db, customer_id, gross):
    eligible = os.getenv("DEMO_MODE") == "1" and db.scalar(
        text("SELECT student_verified FROM users WHERE id=:id"), {"id": customer_id})
    discount = amount(gross * Decimal("0.10")) if eligible else Decimal("0.00")
    return discount, amount(gross - discount)


async def calculate_quote(db, body, customer_id):
    tariff = active_tariff(db, body.type)
    if body.type == "taxi":
        if body.start is None or body.items or body.restaurantId:
            raise HTTPException(422, "Укажите две точки поездки")
        route = await driving_route(body.start, body.end)
        distance = round(route["distance"])
        duration = round(route["duration"])
        gross = amount(Decimal(tariff["base_fare"]) + Decimal(distance) / 1000 * Decimal(tariff["price_per_km"]))
        discount, total = student_discount(db, customer_id, gross)
        return {"total": total, "discount": discount, "tariffId": str(tariff["id"]), "distanceMeters": distance,
                "durationSeconds": duration, "geometry": route["geometry"]}
    if not body.restaurantId or not body.items:
        raise HTTPException(422, "Выберите заведение и блюда")
    if len({line.menuItemId for line in body.items}) != len(body.items):
        raise HTTPException(422, "Повторяющиеся позиции корзины")
    restaurant = one(db, """SELECT r.id,r.name,r.address_id,r.status,a.address_text,a.lat,a.lng
        FROM restaurants r JOIN addresses a ON a.id=r.address_id WHERE r.id=:id""", id=body.restaurantId)
    if not restaurant or restaurant["status"] != "active":
        raise HTTPException(422, "Заведение сейчас недоступно")
    lines, subtotal = [], Decimal(0)
    for line in body.items:
        item = one(db, "SELECT id,name,price,restaurant_id,is_available FROM menu_items WHERE id=:id", id=line.menuItemId)
        if not item or str(item["restaurant_id"]) != body.restaurantId or not item["is_available"]:
            raise HTTPException(422, "Одна из позиций недоступна")
        subtotal += item["price"] * line.quantity
        lines.append({**item, "quantity": line.quantity})
    route = await driving_route(Point(address=restaurant["address_text"], lat=float(restaurant["lat"]),
                                      lng=float(restaurant["lng"])), body.end)
    distance = round(route["distance"])
    delivery = amount(tariff["base_fare"] + tariff["price_per_km"] * Decimal(distance) / 1000)
    discount, total = student_discount(db, customer_id, amount(subtotal + delivery))
    return {"total": total, "discount": discount, "subtotal": amount(subtotal),
            "delivery": delivery, "tariffId": str(tariff["id"]), "lines": lines,
            "restaurant": restaurant, "distanceMeters": distance,
            "durationSeconds": round(route["duration"]), "geometry": route["geometry"]}


@router.get("/config")
def config():
    return {"appName": "YaGo", "city": "Астана", "mapCenter": {"lat": 51.1694, "lng": 71.4491},
            "services": ["taxi", "food", "scooter"], "demoMode": os.getenv("DEMO_MODE") == "1"}


@router.get("/restaurants")
def restaurants(db: DB, q: str = Query("", max_length=100), category: str = ""):
    result = []
    for restaurant in many(db, """SELECT r.id,r.name,r.cuisine,a.address_text,a.lat,a.lng FROM restaurants r
        JOIN addresses a ON a.id=r.address_id WHERE r.status='active' AND r.name ILIKE :q ORDER BY r.name LIMIT 100""", q=f"%{q}%"):
        menu = many(db, """SELECT i.id,i.name,i.description,i.price,i.is_available,c.name category
            FROM menu_items i JOIN menu_categories c ON c.id=i.category_id
            WHERE i.restaurant_id=:id AND (:category='' OR c.name=:category) ORDER BY c.name,i.name""",
            id=restaurant["id"], category=category)
        result.append({"id": str(restaurant["id"]), "name": restaurant["name"], "cuisine": restaurant["cuisine"],
            "address": restaurant["address_text"], "lat": float(restaurant["lat"]), "lng": float(restaurant["lng"]),
            "menu": [{**x, "id": str(x["id"]), "price": str(x["price"])} for x in menu]})
    return result


@router.post("/quotes")
async def quote(body: QuoteInput, user: User, db: DB):
    result = await calculate_quote(db, body, user["id"])
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in result.items() if k not in {"lines", "restaurant"}}


@router.get("/orders")
def orders(user: User, db: DB, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    if "admin" in user["roles"] or "operator" in user["roles"]:
        ids = db.execute(text("SELECT id FROM orders ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), {"limit": limit, "offset": offset}).scalars()
    elif "performer" in user["roles"] or "driver" in user["roles"] or "courier" in user["roles"]:
        ids = db.execute(text("""SELECT o.id FROM orders o JOIN performers p ON p.id=o.performer_id
            WHERE p.user_id=:user ORDER BY o.created_at DESC LIMIT :limit OFFSET :offset"""),
            {"user": user["id"], "limit": limit, "offset": offset}).scalars()
    else:
        ids = db.execute(text("SELECT id FROM orders WHERE customer_id=:user ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"user": user["id"], "limit": limit, "offset": offset}).scalars()
    return [order_view(db, x) for x in ids]


@router.get("/orders/{order_id}")
def get_order(order_id: str, user: User, db: DB):
    order = order_view(db, order_id)
    allowed = order["customerId"] == user["id"] or bool({"admin", "operator"} & set(user["roles"]))
    if not allowed and order["performerId"]:
        allowed = bool(one(db, "SELECT 1 FROM performers WHERE id=:id AND user_id=:user", id=order["performerId"], user=user["id"]))
    if not allowed:
        raise HTTPException(404, "Заказ не найден")
    return order


@router.post("/orders", status_code=201)
async def create_order(body: CreateOrder, user: User, db: DB,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)]):
    require(user, "client")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"order:{user['id']}:{idempotency_key}"})
    payload_hash = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    old = one(db, "SELECT id,request_hash FROM orders WHERE customer_id=:user AND idempotency_key=:key",
        user=user["id"], key=idempotency_key)
    if old:
        if old["request_hash"] != payload_hash:
            raise HTTPException(409, "Этот ключ уже использован для другого заказа")
        return order_view(db, old["id"])
    result = await calculate_quote(db, body, user["id"])
    if body.tariffId != result["tariffId"] or amount(body.quotedTotal) != result["total"]:
        raise HTTPException(409, {"message": "Стоимость изменилась. Подтвердите новую цену", "total": str(result["total"]), "tariffId": result["tariffId"]})
    if body.type == "food":
        pickup_id = result["restaurant"]["address_id"]
    else:
        pickup_id = db.execute(text("INSERT INTO addresses(address_text,lat,lng) VALUES (:name,:lat,:lng) RETURNING id"),
            {"name": body.start.address, "lat": body.start.lat, "lng": body.start.lng}).scalar_one()
    dropoff_id = db.execute(text("INSERT INTO addresses(address_text,lat,lng) VALUES (:name,:lat,:lng) RETURNING id"),
        {"name": body.end.address, "lat": body.end.lat, "lng": body.end.lng}).scalar_one()
    pickup_snapshot = result["restaurant"]["address_text"] if body.type == "food" else body.start.address
    order_id = db.execute(text("""INSERT INTO orders(customer_id,service_type_code,status_code,tariff_id,
        pickup_address_id,dropoff_address_id,restaurant_id,total_amount,discount_amount,distance_meters,duration_seconds,
        idempotency_key,request_hash,pickup_snapshot,dropoff_snapshot,
        pickup_lat_snapshot,pickup_lng_snapshot,dropoff_lat_snapshot,dropoff_lng_snapshot,
        restaurant_name_snapshot,delivery_amount,route_geometry)
        VALUES (:user,:service,'pending',:tariff,:pickup,:dropoff,:restaurant,
        :total,:discount,:distance,:duration,:key,:hash,:pickup_snapshot,:dropoff_snapshot,
        :pickup_lat,:pickup_lng,:dropoff_lat,:dropoff_lng,:restaurant_name,:delivery,CAST(:route AS jsonb)) RETURNING id"""),
        {"user": user["id"], "service": body.type, "tariff": result["tariffId"], "pickup": pickup_id,
         "dropoff": dropoff_id, "restaurant": body.restaurantId if body.type == "food" else None,
         "total": result["total"], "discount": result["discount"],
         "distance": result.get("distanceMeters"), "duration": result.get("durationSeconds"),
         "key": idempotency_key, "hash": payload_hash,
         "pickup_snapshot": pickup_snapshot, "dropoff_snapshot": body.end.address,
         "pickup_lat": result["restaurant"]["lat"] if body.type == "food" else body.start.lat,
         "pickup_lng": result["restaurant"]["lng"] if body.type == "food" else body.start.lng,
         "dropoff_lat": body.end.lat, "dropoff_lng": body.end.lng,
         "restaurant_name": result["restaurant"]["name"] if body.type == "food" else None,
         "delivery": result["delivery"] if body.type == "food" else None,
         "route": json.dumps(result["geometry"])}).scalar_one()
    if body.type == "food":
        for item in result["lines"]:
            db.execute(text("""INSERT INTO order_items(order_id,menu_item_id,quantity,unit_price,item_name_snapshot)
                VALUES (:order,:item,:quantity,:price,:name)"""),
                {"order": order_id, "item": item["id"], "quantity": item["quantity"],
                 "price": item["price"], "name": item["name"]})
    db.execute(text("INSERT INTO order_status_history(order_id,status_code,changed_by_user_id) VALUES (:id,'pending',:user)"),
        {"id": order_id, "user": user["id"]})
    audit(db, user["id"], "order_create", "order", order_id)
    db.commit()
    created = order_view(db, order_id)
    await publish("orderCreated", created)
    return created


class StatusInput(BaseModel):
    status: Literal["assigned", "accepted", "arriving", "preparing", "picked_up", "in_progress", "completed", "cancelled"]


TRANSITIONS = {
    "taxi": {"pending": {"assigned"}, "assigned": {"accepted"}, "accepted": {"arriving"},
             "arriving": {"in_progress"}, "in_progress": {"completed"}},
    "food": {"pending": {"preparing"}, "preparing": {"assigned"},
             "assigned": {"accepted"}, "accepted": {"picked_up"}, "picked_up": {"completed"}},
}


@router.patch("/orders/{order_id}/status")
async def update_status(order_id: str, body: StatusInput, user: User, db: DB):
    order = one(db, "SELECT * FROM orders WHERE id=:id FOR UPDATE", id=order_id)
    if not order:
        raise HTTPException(404, "Заказ не найден")
    old, new = order["status_code"], body.status
    staff = bool({"operator", "admin"} & set(user["roles"]))
    owner = str(order["customer_id"]) == user["id"]
    performer = bool(order["performer_id"] and one(db, "SELECT 1 FROM performers WHERE id=:id AND user_id=:user",
        id=order["performer_id"], user=user["id"]))
    if new == "cancelled":
        if old not in {"pending", "preparing", "assigned"} or not (owner or staff):
            raise HTTPException(409, "Отменить этот заказ уже нельзя")
    elif new not in TRANSITIONS.get(order["service_type_code"], {}).get(old, set()):
        raise HTTPException(409, "Недопустимый переход статуса")
    elif new in {"assigned", "preparing"} and not staff:
        raise HTTPException(403, "Требуются права оператора")
    elif new in {"accepted", "arriving", "picked_up", "in_progress", "completed"} and not performer:
        raise HTTPException(403, "Заказ назначен другому исполнителю")
    if new == "assigned":
        kind = "driver" if order["service_type_code"] == "taxi" else "courier"
        origin = one(db, """SELECT coalesce(o.pickup_lat_snapshot,a.lat) lat,
            coalesce(o.pickup_lng_snapshot,a.lng) lng FROM orders o
            JOIN addresses a ON a.id=o.pickup_address_id WHERE o.id=:id""", id=order_id)
        agent = one(db, """SELECT p.id FROM performers p
            LEFT JOIN addresses position ON position.id=p.address_id
            WHERE p.type=:kind AND p.status='available'
            ORDER BY position.id IS NULL,
              ST_DistanceSphere(ST_SetSRID(ST_MakePoint(position.lng,position.lat),4326),
                ST_SetSRID(ST_MakePoint(:lng,:lat),4326)) NULLS LAST,
              p.id FOR UPDATE OF p SKIP LOCKED LIMIT 1""",
            kind=kind, lat=origin["lat"], lng=origin["lng"])
        if not agent:
            raise HTTPException(409, "Свободных исполнителей нет")
        db.execute(text("UPDATE performers SET status='busy' WHERE id=:id"), {"id": agent["id"]})
        db.execute(text("UPDATE orders SET performer_id=:performer WHERE id=:id"), {"performer": agent["id"], "id": order_id})
    db.execute(text("""UPDATE orders SET status_code=:status,
        accepted_at=CASE WHEN :is_accepted THEN now() ELSE accepted_at END,
        completed_at=CASE WHEN :is_completed THEN now() ELSE completed_at END WHERE id=:id"""),
        {"status": new, "id": order_id, "is_accepted": new == "accepted", "is_completed": new == "completed"})
    if new in {"completed", "cancelled"} and order["performer_id"]:
        db.execute(text("UPDATE performers SET status='available' WHERE id=:id"), {"id": order["performer_id"]})
    if new == "completed":
        db.execute(text("INSERT INTO payments(order_id,amount) VALUES (:id,:amount) ON CONFLICT (order_id) DO NOTHING"),
            {"id": order_id, "amount": order["total_amount"]})
    db.execute(text("""INSERT INTO order_status_history(order_id,from_status,status_code,changed_by_user_id)
        VALUES (:id,:previous,:status,:user)"""),
        {"id": order_id, "status": new, "user": user["id"], "previous": old})
    audit(db, user["id"], "order_status", "order", order_id)
    db.commit()
    updated = order_view(db, order_id)
    await publish("orderStatusUpdated", updated)
    return updated


class ReviewInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field("", max_length=1000)


@router.post("/orders/{order_id}/review", status_code=201)
def review(order_id: str, body: ReviewInput, user: User, db: DB):
    order = one(db, "SELECT customer_id,status_code FROM orders WHERE id=:id", id=order_id)
    if not order or str(order["customer_id"]) != user["id"]:
        raise HTTPException(404, "Заказ не найден")
    if order["status_code"] != "completed":
        raise HTTPException(409, "Отзыв доступен после завершения")
    if one(db, "SELECT 1 FROM reviews WHERE order_id=:id", id=order_id):
        raise HTTPException(409, "Отзыв уже оставлен")
    db.execute(text("INSERT INTO reviews(order_id,customer_id,rating,comment) VALUES (:id,:user,:rating,:comment)"),
        {"id": order_id, "user": user["id"], "rating": body.rating, "comment": body.comment})
    db.commit()
    return {"ok": True}


def release_expired(db):
    expired = db.execute(text("""UPDATE scooter_reservations SET status='expired'
        WHERE status='active' AND expires_at<=now() RETURNING scooter_id""")).scalars().all()
    for scooter_id in expired:
        db.execute(text("UPDATE scooters SET status='available' WHERE id=:id AND status='reserved'"), {"id": scooter_id})


def scooter_view(row):
    return {"id": str(row["id"]), "code": row["code"], "lat": float(row["lat"]),
            "lng": float(row["lng"]), "battery": row["battery_percent"], "status": row["status"]}


@router.get("/scooters")
def scooters(db: DB, user: User):
    release_expired(db)
    db.commit()
    return [scooter_view(r) for r in many(db, "SELECT * FROM scooters WHERE status='available' ORDER BY code")]


@router.get("/zones")
def zones(db: DB):
    return [{"id": str(r["id"]), "name": r["name"], "geometry": json.loads(r["geometry"])}
        for r in many(db, "SELECT id,name,ST_AsGeoJSON(boundary) geometry FROM parking_zones WHERE active ORDER BY name")]


def rental_view(db, rental_id):
    row = one(db, """SELECT r.*,s.code scooter_code,s.lat scooter_lat,s.lng scooter_lng,
        t.name tariff_name,t.base_fare,t.price_per_minute
        FROM scooter_rentals r JOIN scooters s ON s.id=r.scooter_id
        JOIN tariffs t ON t.id=r.tariff_id WHERE r.id=:id""", id=rental_id)
    if not row:
        raise HTTPException(404, "Аренда не найдена")
    duration = int(((row["ended_at"] or datetime.now(timezone.utc)) - row["started_at"]).total_seconds())
    return {"id": str(row["id"]), "reservationId": str(row["reservation_id"]),
            "scooterId": str(row["scooter_id"]), "scooterCode": row["scooter_code"],
            "customerId": str(row["customer_id"]), "status": row["status"],
            "tariff": {"id": str(row["tariff_id"]), "name": row["tariff_name"],
                       "baseFare": str(row["base_fare"]), "pricePerMinute": str(row["price_per_minute"])},
            "startedAt": row["started_at"], "endedAt": row["ended_at"],
            "durationSeconds": duration, "total": str(row["total_amount"]) if row["total_amount"] is not None else None}


@router.get("/rentals")
def rentals(user: User, db: DB, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    release_expired(db)
    db.commit()
    if {"operator", "admin"} & set(user["roles"]):
        ids = db.execute(text("SELECT id FROM scooter_rentals ORDER BY started_at DESC LIMIT :limit OFFSET :offset"),
            {"limit": limit, "offset": offset}).scalars()
    else:
        ids = db.execute(text("SELECT id FROM scooter_rentals WHERE customer_id=:user ORDER BY started_at DESC LIMIT :limit OFFSET :offset"),
            {"user": user["id"], "limit": limit, "offset": offset}).scalars()
    return [rental_view(db, x) for x in ids]


class ReserveInput(BaseModel):
    scooterId: str


@router.post("/scooters/reserve", status_code=201)
def reserve(body: ReserveInput, user: User, db: DB,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)]):
    require(user, "client")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"reserve:{user['id']}:{idempotency_key}"})
    old = one(db, "SELECT * FROM scooter_reservations WHERE customer_id=:user AND idempotency_key=:key",
        user=user["id"], key=idempotency_key)
    if old:
        if str(old["scooter_id"]) != body.scooterId:
            raise HTTPException(409, "Этот ключ уже использован для другого самоката")
        return {"id": str(old["id"]), "scooterId": str(old["scooter_id"]),
                "status": old["status"], "expiresAt": old["expires_at"]}
    release_expired(db)
    # Lock user and scooter in a fixed order; partial unique indexes are the final safeguard.
    db.execute(text("SELECT id FROM users WHERE id=:id FOR UPDATE"), {"id": user["id"]}).first()
    scooter = one(db, "SELECT * FROM scooters WHERE id=:id FOR UPDATE", id=body.scooterId)
    if not scooter or scooter["status"] != "available":
        raise HTTPException(409, "Самокат недоступен")
    if one(db, "SELECT 1 FROM scooter_reservations WHERE customer_id=:user AND status='active'", user=user["id"]) or \
       one(db, "SELECT 1 FROM scooter_rentals WHERE customer_id=:user AND status='active'", user=user["id"]):
        raise HTTPException(409, "У вас уже есть бронь или аренда")
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    reservation_id = db.execute(text("""INSERT INTO scooter_reservations(scooter_id,customer_id,expires_at,idempotency_key)
        VALUES (:scooter,:user,:expiry,:key) RETURNING id"""),
        {"scooter": body.scooterId, "user": user["id"], "expiry": expiry, "key": idempotency_key}).scalar_one()
    db.execute(text("UPDATE scooters SET status='reserved' WHERE id=:id"), {"id": body.scooterId})
    audit(db, user["id"], "scooter_reserve", "reservation", reservation_id)
    db.commit()
    return {"id": str(reservation_id), "scooterId": body.scooterId, "status": "active", "expiresAt": expiry}


@router.get("/reservations")
def reservations(user: User, db: DB):
    release_expired(db)
    db.commit()
    return [{"id": str(r["id"]), "scooterId": str(r["scooter_id"]), "status": r["status"],
             "expiresAt": r["expires_at"], "code": r["code"]} for r in many(db, """
        SELECT r.*,s.code FROM scooter_reservations r JOIN scooters s ON s.id=r.scooter_id
        WHERE r.customer_id=:user AND r.status='active' ORDER BY r.created_at DESC""", user=user["id"])]


@router.get("/reservations/{reservation_id}/demo-qr")
def demo_qr(reservation_id: str, user: User, db: DB):
    if os.getenv("DEMO_MODE") != "1":
        raise HTTPException(404, "Недоступно")
    qr = one(db, """SELECT s.qr_code FROM scooter_reservations r JOIN scooters s ON s.id=r.scooter_id
        WHERE r.id=:id AND r.customer_id=:user AND r.status='active' AND r.expires_at>now()""",
        id=reservation_id, user=user["id"])
    if not qr:
        raise HTTPException(404, "Бронь не найдена")
    return {"qrCode": qr["qr_code"], "emulated": True}


class StartInput(BaseModel):
    qrCode: str = Field(min_length=3, max_length=80)


@router.post("/reservations/{reservation_id}/start")
def start_rental(reservation_id: str, body: StartInput, user: User, db: DB):
    reservation = one(db, "SELECT * FROM scooter_reservations WHERE id=:id FOR UPDATE", id=reservation_id)
    if not reservation or str(reservation["customer_id"]) != user["id"]:
        raise HTTPException(404, "Бронь не найдена")
    scooter = one(db, "SELECT * FROM scooters WHERE id=:id FOR UPDATE", id=reservation["scooter_id"])
    if body.qrCode != scooter["qr_code"]:
        raise HTTPException(422, "QR-код не подходит к этому самокату")
    existing = one(db, "SELECT id FROM scooter_rentals WHERE reservation_id=:id", id=reservation_id)
    if existing:
        return rental_view(db, existing["id"])
    if reservation["status"] != "active" or reservation["expires_at"] <= datetime.now(timezone.utc):
        release_expired(db)
        db.commit()
        raise HTTPException(409, "Срок бронирования истёк")
    tariff = active_tariff(db, "scooter")
    rental_id = db.execute(text("""INSERT INTO scooter_rentals(reservation_id,scooter_id,customer_id,tariff_id)
        VALUES (:reservation,:scooter,:user,:tariff) RETURNING id"""),
        {"reservation": reservation_id, "scooter": scooter["id"], "user": user["id"], "tariff": tariff["id"]}).scalar_one()
    db.execute(text("UPDATE scooter_reservations SET status='started' WHERE id=:id"), {"id": reservation_id})
    db.execute(text("UPDATE scooters SET status='in_use' WHERE id=:id"), {"id": scooter["id"]})
    db.execute(text("INSERT INTO rental_status_history(rental_id,to_status,actor_id) VALUES (:id,'active',:user)"),
        {"id": rental_id, "user": user["id"]})
    audit(db, user["id"], "rental_start", "rental", rental_id)
    db.commit()
    return rental_view(db, rental_id)


class EndInput(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/rentals/{rental_id}/finish")
def finish_rental(rental_id: str, body: EndInput, user: User, db: DB):
    rental = one(db, "SELECT * FROM scooter_rentals WHERE id=:id FOR UPDATE", id=rental_id)
    if not rental or str(rental["customer_id"]) != user["id"]:
        raise HTTPException(404, "Аренда не найдена")
    if rental["status"] == "completed":
        return rental_view(db, rental_id)
    in_zone = one(db, """SELECT id FROM parking_zones WHERE active
        AND ST_Covers(boundary, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)) LIMIT 1""",
        lng=body.lng, lat=body.lat)
    if not in_zone:
        raise HTTPException(409, "Завершите аренду в зелёной зоне парковки на карте")
    tariff = one(db, "SELECT base_fare,price_per_minute FROM tariffs WHERE id=:id", id=rental["tariff_id"])
    now = datetime.now(timezone.utc)
    minutes = max(1, int((Decimal(str((now-rental["started_at"]).total_seconds())) / 60).to_integral_value(rounding=ROUND_CEILING)))
    total = amount(tariff["base_fare"] + minutes * tariff["price_per_minute"])
    db.execute(text("""UPDATE scooter_rentals SET status='completed',ended_at=:now,end_lat=:lat,end_lng=:lng,
        total_amount=:total WHERE id=:id"""),
        {"now": now, "lat": body.lat, "lng": body.lng, "total": total, "id": rental_id})
    db.execute(text("UPDATE scooters SET status='available',lat=:lat,lng=:lng WHERE id=:id"),
        {"lat": body.lat, "lng": body.lng, "id": rental["scooter_id"]})
    db.execute(text("INSERT INTO payments(rental_id,amount) VALUES (:id,:amount) ON CONFLICT (rental_id) DO NOTHING"),
        {"id": rental_id, "amount": total})
    db.execute(text("""INSERT INTO rental_status_history(rental_id,from_status,to_status,actor_id)
        VALUES (:id,'active','completed',:user)"""), {"id": rental_id, "user": user["id"]})
    audit(db, user["id"], "rental_finish", "rental", rental_id)
    db.commit()
    return rental_view(db, rental_id)


class MenuUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field("", max_length=1000)
    price: Decimal = Field(ge=0)
    category: str = Field(min_length=2, max_length=120)
    available: bool = True


class RestaurantInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    cuisine: str = Field(min_length=2, max_length=120)
    address: Point


@router.post("/operator/restaurants", status_code=201)
def create_restaurant(body: RestaurantInput, user: User, db: DB):
    require(user, "operator", "admin")
    address_id = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
        VALUES (:name,:lat,:lng) RETURNING id"""),
        {"name": body.address.address, "lat": body.address.lat, "lng": body.address.lng}).scalar_one()
    restaurant_id = db.execute(text("""INSERT INTO restaurants(address_id,name,cuisine)
        VALUES (:address,:name,:cuisine) RETURNING id"""),
        {"address": address_id, "name": body.name, "cuisine": body.cuisine}).scalar_one()
    audit(db, user["id"], "restaurant_create", "restaurant", restaurant_id)
    db.commit()
    return {"id": str(restaurant_id)}


class RestaurantStatus(BaseModel):
    active: bool


@router.patch("/operator/restaurants/{restaurant_id}/status")
def restaurant_status(restaurant_id: str, body: RestaurantStatus, user: User, db: DB):
    require(user, "operator", "admin")
    updated = db.execute(text("UPDATE restaurants SET status=:status WHERE id=:id"),
                         {"status": "active" if body.active else "archived", "id": restaurant_id})
    if not updated.rowcount:
        raise HTTPException(404, "Заведение не найдено")
    audit(db, user["id"], "restaurant_status", "restaurant", restaurant_id)
    db.commit()
    return {"ok": True}


@router.post("/operator/restaurants/{restaurant_id}/menu", status_code=201)
def add_menu_item(restaurant_id: str, body: MenuUpdate, user: User, db: DB):
    require(user, "operator", "admin")
    if not one(db, "SELECT 1 FROM restaurants WHERE id=:id", id=restaurant_id):
        raise HTTPException(404, "Заведение не найдено")
    category = one(db, "SELECT id FROM menu_categories WHERE name=:name", name=body.category)
    if not category:
        category = one(db, "INSERT INTO menu_categories(name) VALUES (:name) RETURNING id", name=body.category)
    item_id = db.execute(text("""INSERT INTO menu_items(restaurant_id,category_id,name,description,price,is_available)
        VALUES (:restaurant,:category,:name,:description,:price,:available) RETURNING id"""),
        {"restaurant": restaurant_id, "category": category["id"], "name": body.name,
         "description": body.description, "price": amount(body.price), "available": body.available}).scalar_one()
    audit(db, user["id"], "menu_create", "menu_item", item_id)
    db.commit()
    return {"id": str(item_id)}


@router.patch("/operator/menu/{item_id}")
def edit_menu_item(item_id: str, body: MenuUpdate, user: User, db: DB):
    require(user, "operator", "admin")
    if not one(db, "SELECT 1 FROM menu_items WHERE id=:id", id=item_id):
        raise HTTPException(404, "Блюдо не найдено")
    category = one(db, "SELECT id FROM menu_categories WHERE name=:name", name=body.category)
    if not category:
        category = one(db, "INSERT INTO menu_categories(name) VALUES (:name) RETURNING id", name=body.category)
    db.execute(text("""UPDATE menu_items SET name=:name,description=:description,price=:price,
        category_id=:category,is_available=:available WHERE id=:id"""),
        {"id": item_id, "name": body.name, "description": body.description,
         "price": amount(body.price), "category": category["id"], "available": body.available})
    audit(db, user["id"], "menu_update", "menu_item", item_id)
    db.commit()
    return {"ok": True}


class ScooterUpdate(BaseModel):
    status: Literal["available", "maintenance", "blocked"]
    battery: int = Field(ge=0, le=100)


class ScooterCreate(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    qrCode: str = Field(min_length=3, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    battery: int = Field(ge=0, le=100)


@router.post("/operator/scooters", status_code=201)
def create_scooter(body: ScooterCreate, user: User, db: DB):
    require(user, "operator", "admin")
    if one(db, "SELECT 1 FROM scooters WHERE code=:code OR qr_code=:qr", code=body.code, qr=body.qrCode):
        raise HTTPException(409, "Номер или QR-код уже используется")
    scooter_id = db.execute(text("""INSERT INTO scooters(code,qr_code,lat,lng,battery_percent)
        VALUES (:code,:qr,:lat,:lng,:battery) RETURNING id"""),
        {"code": body.code, "qr": body.qrCode, "lat": body.lat,
         "lng": body.lng, "battery": body.battery}).scalar_one()
    audit(db, user["id"], "scooter_create", "scooter", scooter_id)
    db.commit()
    return {"id": str(scooter_id)}


class ZoneInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)


class ZoneUpdate(ZoneInput):
    active: bool


@router.get("/operator/zones")
def operator_zones(user: User, db: DB):
    require(user, "operator", "admin")
    return [{"id": str(r["id"]), "name": r["name"], "active": r["active"],
             "geometry": json.loads(r["geometry"])} for r in many(db,
        "SELECT id,name,active,ST_AsGeoJSON(boundary) geometry FROM parking_zones ORDER BY name")]


@router.post("/operator/zones", status_code=201)
def create_zone(body: ZoneInput, user: User, db: DB):
    require(user, "operator", "admin")
    if body.north <= body.south or body.east <= body.west:
        raise HTTPException(422, "Неверные границы зоны")
    if one(db, "SELECT 1 FROM parking_zones WHERE name=:name", name=body.name):
        raise HTTPException(409, "Зона с этим названием уже есть")
    zone_id = db.execute(text("""INSERT INTO parking_zones(name,boundary)
        VALUES (:name,ST_MakeEnvelope(:west,:south,:east,:north,4326)) RETURNING id"""),
        body.model_dump()).scalar_one()
    audit(db, user["id"], "zone_create", "parking_zone", zone_id)
    db.commit()
    return {"id": str(zone_id)}


@router.patch("/operator/zones/{zone_id}/status")
def zone_status(zone_id: str, body: RestaurantStatus, user: User, db: DB):
    require(user, "operator", "admin")
    updated = db.execute(text("UPDATE parking_zones SET active=:active WHERE id=:id"),
                         {"active": body.active, "id": zone_id})
    if not updated.rowcount:
        raise HTTPException(404, "Зона не найдена")
    audit(db, user["id"], "zone_status", "parking_zone", zone_id)
    db.commit()
    return {"ok": True}


@router.patch("/operator/zones/{zone_id}")
def edit_zone(zone_id: str, body: ZoneUpdate, user: User, db: DB):
    require(user, "operator", "admin")
    if body.north <= body.south or body.east <= body.west:
        raise HTTPException(422, "Неверные границы зоны")
    if one(db, "SELECT 1 FROM parking_zones WHERE name=:name AND id<>:id", name=body.name, id=zone_id):
        raise HTTPException(409, "Зона с этим названием уже есть")
    updated = db.execute(text("""UPDATE parking_zones SET name=:name,active=:active,
        boundary=ST_MakeEnvelope(:west,:south,:east,:north,4326) WHERE id=:id"""),
        {**body.model_dump(), "id": zone_id})
    if not updated.rowcount:
        raise HTTPException(404, "Зона не найдена")
    audit(db, user["id"], "zone_update", "parking_zone", zone_id)
    db.commit()
    return {"ok": True}


@router.delete("/operator/zones/{zone_id}")
def delete_zone(zone_id: str, user: User, db: DB):
    require(user, "operator", "admin")
    zone = one(db, "SELECT active FROM parking_zones WHERE id=:id FOR UPDATE", id=zone_id)
    if not zone:
        raise HTTPException(404, "Зона не найдена")
    if zone["active"]:
        raise HTTPException(409, "Сначала архивируйте зону")
    db.execute(text("DELETE FROM parking_zones WHERE id=:id"), {"id": zone_id})
    audit(db, user["id"], "zone_delete", "parking_zone", zone_id)
    db.commit()
    return {"ok": True}


@router.get("/operator/scooters")
def operator_scooters(user: User, db: DB):
    require(user, "operator", "admin")
    return [scooter_view(r) for r in many(db, "SELECT * FROM scooters ORDER BY code")]


@router.patch("/operator/scooters/{scooter_id}")
def edit_scooter(scooter_id: str, body: ScooterUpdate, user: User, db: DB):
    require(user, "operator", "admin")
    scooter = one(db, "SELECT * FROM scooters WHERE id=:id FOR UPDATE", id=scooter_id)
    if not scooter:
        raise HTTPException(404, "Самокат не найден")
    if scooter["status"] in {"reserved", "in_use"}:
        raise HTTPException(409, "Самокат сейчас используется")
    db.execute(text("UPDATE scooters SET status=:status,battery_percent=:battery WHERE id=:id"),
        {"status": body.status, "battery": body.battery, "id": scooter_id})
    audit(db, user["id"], "scooter_update", "scooter", scooter_id)
    db.commit()
    return {"ok": True}


class TariffInput(BaseModel):
    service: Literal["taxi", "food", "scooter"]
    name: str = Field(min_length=2, max_length=120)
    baseFare: Decimal = Field(ge=0)
    pricePerKm: Decimal = Field(ge=0)
    pricePerMinute: Decimal = Field(ge=0)


@router.get("/tariffs")
def tariffs(db: DB):
    return [{"id": str(t["id"]), "service": t["service_type_code"], "name": t["name"],
             "baseFare": str(t["base_fare"]), "pricePerKm": str(t["price_per_km"]),
             "pricePerMinute": str(t["price_per_minute"])}
            for t in many(db, """SELECT DISTINCT ON (service_type_code) * FROM tariffs
                WHERE service_type_code IN ('taxi','food','scooter') AND valid_from<=now()
                AND (valid_to IS NULL OR valid_to>now()) ORDER BY service_type_code,valid_from DESC,id DESC""")]


@router.get("/operator/tariffs")
def operator_tariffs(user: User, db: DB):
    require(user, "operator", "admin")
    return [{"id": str(t["id"]), "service": t["service_type_code"], "name": t["name"],
             "baseFare": str(t["base_fare"]), "pricePerKm": str(t["price_per_km"]),
             "pricePerMinute": str(t["price_per_minute"]), "validFrom": t["valid_from"],
             "validTo": t["valid_to"], "used": t["used"]} for t in many(db, """
        SELECT t.*, EXISTS(SELECT 1 FROM orders WHERE tariff_id=t.id)
          OR EXISTS(SELECT 1 FROM scooter_rentals WHERE tariff_id=t.id) used
        FROM tariffs t WHERE service_type_code IN ('taxi','food','scooter')
        ORDER BY valid_from DESC,id DESC""")]


def editable_tariff(db, tariff_id):
    tariff = one(db, """SELECT id,service_type_code FROM tariffs WHERE id=:id FOR UPDATE""", id=tariff_id)
    if not tariff:
        raise HTTPException(404, "Тариф не найден")
    if one(db, """SELECT 1 FROM orders WHERE tariff_id=:id UNION ALL
        SELECT 1 FROM scooter_rentals WHERE tariff_id=:id LIMIT 1""", id=tariff_id):
        raise HTTPException(409, "Использованную версию тарифа менять нельзя. Создайте новую")
    return tariff


@router.post("/operator/tariffs", status_code=201)
def add_tariff(body: TariffInput, user: User, db: DB):
    require(user, "operator", "admin")
    tariff_id = db.execute(text("""INSERT INTO tariffs(service_type_code,name,base_fare,price_per_km,
        price_per_minute,valid_from) VALUES (:service,:name,:base,:km,:minute,now()) RETURNING id"""),
        {"service": body.service, "name": body.name, "base": amount(body.baseFare),
         "km": amount(body.pricePerKm), "minute": amount(body.pricePerMinute)}).scalar_one()
    audit(db, user["id"], "tariff_create", "tariff", tariff_id)
    db.commit()
    return {"id": str(tariff_id)}


@router.patch("/operator/tariffs/{tariff_id}")
def edit_tariff(tariff_id: str, body: TariffInput, user: User, db: DB):
    require(user, "operator", "admin")
    editable_tariff(db, tariff_id)
    db.execute(text("""UPDATE tariffs SET service_type_code=:service,name=:name,
        base_fare=:base,price_per_km=:km,price_per_minute=:minute WHERE id=:id"""),
        {"id": tariff_id, "service": body.service, "name": body.name,
         "base": amount(body.baseFare), "km": amount(body.pricePerKm),
         "minute": amount(body.pricePerMinute)})
    audit(db, user["id"], "tariff_update", "tariff", tariff_id)
    db.commit()
    return {"ok": True}


@router.delete("/operator/tariffs/{tariff_id}")
def delete_tariff(tariff_id: str, user: User, db: DB):
    require(user, "operator", "admin")
    tariff = editable_tariff(db, tariff_id)
    remaining = one(db, """SELECT 1 FROM tariffs WHERE id<>:id AND service_type_code=:service
        AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now()) LIMIT 1""",
        id=tariff_id, service=tariff["service_type_code"])
    if not remaining:
        raise HTTPException(409, "Сначала создайте замену действующему тарифу")
    db.execute(text("DELETE FROM tariffs WHERE id=:id"), {"id": tariff_id})
    audit(db, user["id"], "tariff_delete", "tariff", tariff_id)
    db.commit()
    return {"ok": True}


class ProfileUpdate(BaseModel):
    fullName: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=32)


@router.patch("/profile")
def profile(body: ProfileUpdate, user: User, db: DB):
    db.execute(text("UPDATE users SET full_name=:name,phone=:phone WHERE id=:id"),
        {"name": body.fullName.strip(), "phone": body.phone, "id": user["id"]})
    audit(db, user["id"], "profile_update", "user", user["id"])
    db.commit()
    return {"ok": True}


@router.get("/admin/users")
def admin_users(user: User, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    require(user, "admin")
    result = []
    for u in many(db, "SELECT id,email,full_name,is_active FROM users ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
                  limit=limit, offset=offset):
        result.append({"id": str(u["id"]), "email": u["email"], "name": u["full_name"],
            "active": u["is_active"], "roles": db.execute(text("SELECT role_code FROM user_roles WHERE user_id=:id"), {"id": u["id"]}).scalars().all()})
    return result


class RoleInput(BaseModel):
    role: Literal["client", "performer", "operator", "admin"]
    enabled: bool


@router.patch("/admin/users/{user_id}/role")
def change_role(user_id: str, body: RoleInput, user: User, db: DB):
    require(user, "admin")
    if not one(db, "SELECT 1 FROM users WHERE id=:id", id=user_id):
        raise HTTPException(404, "Пользователь не найден")
    if user_id == user["id"] and body.role == "admin" and not body.enabled:
        raise HTTPException(409, "Нельзя убрать собственную роль администратора")
    if body.enabled:
        db.execute(text("INSERT INTO user_roles(user_id,role_code) VALUES (:id,:role) ON CONFLICT DO NOTHING"),
            {"id": user_id, "role": body.role})
    else:
        db.execute(text("DELETE FROM user_roles WHERE user_id=:id AND role_code=:role"),
            {"id": user_id, "role": body.role})
    audit(db, user["id"], "role_change", "user", user_id)
    db.commit()
    return {"ok": True}


@router.get("/admin/audit")
def admin_audit(user: User, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    require(user, "admin")
    return [{**r, "actor_id": str(r["actor_id"]) if r["actor_id"] else None}
        for r in many(db, """SELECT e.actor_id,u.email actor_email,e.action,e.subject_type,e.subject_id,e.created_at
            FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id
            ORDER BY e.id DESC LIMIT :limit OFFSET :offset""",
                      limit=limit, offset=offset)]


@router.get("/admin/login-events")
def admin_login_events(user: User, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    require(user, "admin")
    return many(db, """SELECT e.action,e.created_at,u.email actor_email,e.subject_id email_hash
        FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id
        WHERE e.action IN ('login','login_failed','login_rate_limited',
            'login_2fa','login_2fa_failed','login_2fa_expired')
        ORDER BY e.id DESC LIMIT :limit OFFSET :offset""", limit=limit, offset=offset)


@router.get("/admin/analytics")
def analytics(user: User, db: DB, from_at: datetime | None = None, to_at: datetime | None = None):
    require(user, "admin")
    if from_at and to_at and from_at >= to_at:
        raise HTTPException(422, "Конец периода должен быть позже начала")
    since = from_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
    until = to_at or datetime(9999, 1, 1, tzinfo=timezone.utc)
    return one(db, """SELECT
        (SELECT count(*) FROM orders WHERE created_at>=:since AND created_at<:until) orders,
        (SELECT count(*) FROM orders WHERE status_code='cancelled'
         AND created_at>=:since AND created_at<:until) cancellations,
        (SELECT coalesce(sum(amount),0) FROM payments WHERE status='paid'
         AND created_at>=:since AND created_at<:until) revenue,
        (SELECT round(extract(epoch FROM avg(accepted_at-created_at))/60,1)
         FROM orders WHERE accepted_at IS NOT NULL
         AND created_at>=:since AND created_at<:until) average_wait_minutes""",
        since=since, until=until)


@router.get("/admin/heatmap")
def heatmap(user: User, db: DB, limit: int = Query(100, ge=1, le=500)):
    require(user, "admin")
    return [{"lat": float(r["lat"]), "lng": float(r["lng"]), "count": r["count"]}
        for r in many(db, """SELECT round(coalesce(o.pickup_lat_snapshot,a.lat),3) lat,
            round(coalesce(o.pickup_lng_snapshot,a.lng),3) lng,count(*) count
            FROM orders o JOIN addresses a ON a.id=o.pickup_address_id
            GROUP BY 1,2 ORDER BY count DESC LIMIT :limit""", limit=limit)]


@router.get("/admin/users/{user_id}/sessions")
def admin_user_sessions(user_id: str, user: User, db: DB):
    require(user, "admin")
    if not one(db, "SELECT 1 FROM users WHERE id=:id", id=user_id):
        raise HTTPException(404, "Пользователь не найден")
    return [{"id": str(r["id"]), "createdAt": r["created_at"], "expiresAt": r["expires_at"]}
        for r in many(db, """SELECT id,created_at,expires_at FROM sessions
            WHERE user_id=:id AND revoked_at IS NULL AND expires_at>now()
            ORDER BY created_at DESC""", id=user_id)]


@router.delete("/admin/sessions/{session_id}")
def admin_revoke_session(session_id: str, user: User, db: DB):
    require(user, "admin")
    result = db.execute(text("UPDATE sessions SET revoked_at=now() WHERE id=:id AND revoked_at IS NULL"),
                        {"id": session_id})
    if not result.rowcount:
        raise HTTPException(404, "Сессия не найдена")
    audit(db, user["id"], "session_revoke", "session", session_id)
    db.commit()
    return {"ok": True}


@router.get("/couriers")
def couriers(user: User, db: DB):
    require(user, "operator", "admin")
    return [{"id": str(r["id"]), "name": r["full_name"], "role": r["type"], "status": r["status"]}
        for r in many(db, "SELECT p.id,u.full_name,p.type,p.status FROM performers p JOIN users u ON u.id=p.user_id ORDER BY u.full_name")]


class Position(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/trace/{performer_id}")
async def update_position(performer_id: str, body: Position, user: User, db: DB):
    performer = one(db, "SELECT * FROM performers WHERE id=:id", id=performer_id)
    if not performer or str(performer["user_id"]) != user["id"]:
        raise HTTPException(404, "Исполнитель не найден")
    if performer["address_id"]:
        db.execute(text("UPDATE addresses SET lat=:lat,lng=:lng WHERE id=:id"),
            {"lat": body.lat, "lng": body.lng, "id": performer["address_id"]})
    else:
        address_id = db.execute(text("INSERT INTO addresses(address_text,lat,lng) VALUES ('Позиция исполнителя',:lat,:lng) RETURNING id"),
            {"lat": body.lat, "lng": body.lng}).scalar_one()
        db.execute(text("UPDATE performers SET address_id=:address WHERE id=:id"),
            {"address": address_id, "id": performer_id})
    db.commit()
    await publish("driverMoved", {"id": performer_id, "lat": body.lat, "lng": body.lng})
    return {"ok": True}
