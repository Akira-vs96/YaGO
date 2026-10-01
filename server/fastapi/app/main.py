import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.types import JSON


load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

app_name = os.getenv("APP_NAME", "YaGo API")
database_url = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://yago:yago@localhost:5432/yago"
)
osrm_base_url = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
osrm_timeout = float(os.getenv("OSRM_TIMEOUT_SECONDS", "5"))
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
json_type = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    cuisine: Mapped[str] = mapped_column(String(120), nullable=False)
    eta: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    menu: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    restaurant_id: Mapped[str] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    restaurant: Mapped[Restaurant] = relationship(back_populates="menu")


class Performer(Base):
    __tablename__ = "performers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    restaurant_id: Mapped[str | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[dict[str, float]] = mapped_column(json_type, nullable=False)
    end: Mapped[dict[str, float]] = mapped_column(json_type, nullable=False)
    courier_id: Mapped[str | None] = mapped_column(ForeignKey("performers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: f"oi-{uuid4().hex[:12]}")
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[str] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class OrderLineInput(BaseModel):
    menuItemId: str
    quantity: int = Field(ge=1, le=99)


class CreateOrder(BaseModel):
    customer: str = Field(min_length=1, max_length=120)
    type: Literal["food", "taxi"]
    restaurantId: str | None = None
    items: list[OrderLineInput] = Field(default_factory=list, max_length=50)
    start: Coordinates
    end: Coordinates


class StatusUpdate(BaseModel):
    status: Literal["assigned", "in_progress", "completed", "cancelled"]


SEED_RESTAURANTS = [
    ("r1", "Bukhara", 51.1676, 71.4258, "Центральная Азия", 18),
    ("r2", "Caffe Luna", 51.1734, 71.4524, "Кофе и бургеры", 22),
    ("r3", "Sakura Wok", 51.1612, 71.4307, "Японская кухня", 25),
]
SEED_MENU = [
    ("m1", "r1", "Плов", 2200, "Основное"),
    ("m2", "r1", "Самса с курицей", 750, "Закуски"),
    ("m3", "r1", "Чай тан", 500, "Напитки"),
    ("m4", "r2", "Бургер Classic", 1900, "Бургеры"),
    ("m5", "r2", "Картофель фри", 700, "Закуски"),
    ("m6", "r2", "Латте", 650, "Напитки"),
    ("m7", "r3", "Рис с курицей", 2400, "Основное"),
    ("m8", "r3", "Гункан", 990, "Закуски"),
    ("m9", "r3", "Морс", 500, "Напитки"),
]
SEED_PERFORMERS = [
    ("c1", "Ержан", "courier", 51.1688, 71.4441, "available"),
    ("c2", "Дина", "courier", 51.175, 71.4385, "busy"),
    ("c3", "Тимур", "driver", 51.1636, 71.4522, "available"),
]
TAXI_DEMO_FARE = 2800


def seed_database() -> None:
    with SessionLocal.begin() as session:
        if session.scalar(select(Restaurant.id).limit(1)) is None:
            session.add_all(
                Restaurant(id=row[0], name=row[1], lat=row[2], lng=row[3], cuisine=row[4], eta=row[5])
                for row in SEED_RESTAURANTS
            )
            session.add_all(
                MenuItem(id=row[0], restaurant_id=row[1], name=row[2], price=row[3], category=row[4])
                for row in SEED_MENU
            )
        if session.scalar(select(Performer.id).limit(1)) is None:
            session.add_all(
                Performer(id=row[0], name=row[1], role=row[2], lat=row[3], lng=row[4], status=row[5])
                for row in SEED_PERFORMERS
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_database()
    yield
    engine.dispose()


app = FastAPI(title=app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_session():
    with SessionLocal() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]


class EventHub:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def publish(self, event: str, data: dict) -> None:
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        for websocket in tuple(self.connections):
            try:
                await websocket.send_text(message)
            except Exception:
                self.disconnect(websocket)


events = EventHub()


def order_payload(order: Order) -> dict:
    return {
        "id": order.id,
        "customer": order.customer,
        "type": order.type,
        "restaurantId": order.restaurant_id,
        "status": order.status,
        "total": order.total,
        "start": order.start,
        "end": order.end,
        "courierId": order.courier_id,
        "createdAt": order.created_at.isoformat(),
        "items": [
            {
                "id": item.menu_item_id,
                "name": item.name,
                "quantity": item.quantity,
                "unitPrice": item.unit_price,
            }
            for item in order.items
        ],
    }


@app.get("/api/health", tags=["health"])
def health(session: DbSession) -> dict[str, str | bool]:
    session.execute(select(1))
    return {"ok": True, "service": app_name, "db": "connected"}


@app.get("/api/config")
def config() -> dict:
    return {
        "appName": "YaGo",
        "city": "Астана",
        "mapCenter": {"lat": 51.1694, "lng": 71.4491},
        "supportedRoles": ["client", "courier", "driver", "restaurant", "admin"],
    }


@app.get("/api/routes")
async def get_route(
    start_lat: float = Query(alias="startLat", ge=-90, le=90),
    start_lng: float = Query(alias="startLng", ge=-180, le=180),
    end_lat: float = Query(alias="endLat", ge=-90, le=90),
    end_lng: float = Query(alias="endLng", ge=-180, le=180),
) -> dict:
    coordinates = f"{start_lng},{start_lat};{end_lng},{end_lat}"
    try:
        async with httpx.AsyncClient(timeout=osrm_timeout) as client:
            response = await client.get(
                f"{osrm_base_url}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson", "steps": "true"},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Сервис дорожной маршрутизации временно недоступен",
        ) from error

    route = next(iter(result.get("routes", [])), None)
    if result.get("code") != "Ok" or route is None:
        raise HTTPException(status_code=422, detail="Дорожный маршрут для этих точек не найден")

    steps = [
        {
            "name": step.get("name") or "Без названия",
            "distanceMeters": round(step["distance"]),
            "durationSeconds": round(step["duration"]),
            "maneuver": step.get("maneuver", {}).get("type", "continue"),
            "modifier": step.get("maneuver", {}).get("modifier"),
        }
        for leg in route.get("legs", [])
        for step in leg.get("steps", [])
        if step.get("distance", 0) > 0
    ]

    return {
        "provider": "OSRM",
        "profile": "driving",
        "geometry": route["geometry"],
        "distanceMeters": round(route["distance"]),
        "distanceKm": round(route["distance"] / 1000, 1),
        "durationSeconds": round(route["duration"]),
        "durationMinutes": max(1, round(route["duration"] / 60)),
        "steps": steps,
    }


@app.get("/api/restaurants")
def list_restaurants(session: DbSession) -> list[dict]:
    restaurants = session.scalars(
        select(Restaurant).where(Restaurant.active.is_(True)).order_by(Restaurant.name)
    ).all()
    return [
        {
            "id": restaurant.id,
            "name": restaurant.name,
            "lat": restaurant.lat,
            "lng": restaurant.lng,
            "cuisine": restaurant.cuisine,
            "eta": restaurant.eta,
            "menu": [
                {"id": item.id, "name": item.name, "price": item.price, "category": item.category}
                for item in restaurant.menu
            ],
        }
        for restaurant in restaurants
    ]


@app.get("/api/orders")
def list_orders(session: DbSession) -> list[dict]:
    return [order_payload(order) for order in session.scalars(select(Order).order_by(Order.created_at.desc())).all()]


@app.post("/api/orders", status_code=201)
async def create_order(body: CreateOrder, session: DbSession) -> dict:
    order_items = []
    if body.type == "food":
        if not body.restaurantId or session.get(Restaurant, body.restaurantId) is None:
            raise HTTPException(status_code=422, detail="Выберите действующий ресторан")
        if not body.items:
            raise HTTPException(status_code=422, detail="Добавьте хотя бы одну позицию в корзину")
        restaurant_id = body.restaurantId
        for line in body.items:
            menu_item = session.get(MenuItem, line.menuItemId)
            if menu_item is None or menu_item.restaurant_id != restaurant_id:
                raise HTTPException(status_code=422, detail="Позиция меню не принадлежит выбранному ресторану")
            order_items.append(
                OrderItem(
                    menu_item_id=menu_item.id,
                    name=menu_item.name,
                    quantity=line.quantity,
                    unit_price=menu_item.price,
                )
            )
        total = sum(item.quantity * item.unit_price for item in order_items)
    else:
        if body.items:
            raise HTTPException(status_code=422, detail="Корзина еды неприменима к заказу такси")
        restaurant_id = None
        total = TAXI_DEMO_FARE

    order = Order(
        id=f"o-{uuid4().hex[:12]}",
        customer=body.customer.strip(),
        type=body.type,
        restaurant_id=restaurant_id,
        status="pending",
        total=total,
        start=body.start.model_dump(),
        end=body.end.model_dump(),
        created_at=datetime.now(timezone.utc),
        items=order_items,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    result = order_payload(order)
    await events.publish("orderCreated", result)
    return result


@app.patch("/api/orders/{order_id}/status")
async def update_order_status(order_id: str, body: StatusUpdate, session: DbSession) -> dict:
    order = session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    allowed = {
        "pending": {"assigned", "cancelled"},
        "assigned": {"in_progress", "cancelled"},
        "in_progress": {"completed"},
    }
    if body.status not in allowed.get(order.status, set()):
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса заказа")

    if body.status == "assigned":
        performer_role = "driver" if order.type == "taxi" else "courier"
        performer = session.scalar(
            select(Performer)
            .where(Performer.role == performer_role, Performer.status == "available")
            .order_by(Performer.id)
            .with_for_update(skip_locked=True)
        )
        if performer is None:
            raise HTTPException(status_code=409, detail="Нет свободного исполнителя для этого заказа")
        performer.status = "busy"
        order.courier_id = performer.id

    order.status = body.status
    if body.status in {"completed", "cancelled"} and order.courier_id:
        performer = session.scalar(
            select(Performer).where(Performer.id == order.courier_id).with_for_update()
        )
        if performer is not None:
            performer.status = "available"
    session.commit()
    session.refresh(order)
    result = order_payload(order)
    await events.publish("orderStatusUpdated", result)
    return result


@app.get("/api/couriers")
def list_performers(session: DbSession) -> list[dict]:
    return [
        {
            "id": person.id,
            "name": person.name,
            "role": person.role,
            "lat": person.lat,
            "lng": person.lng,
            "status": person.status,
        }
        for person in session.scalars(select(Performer).order_by(Performer.id)).all()
    ]


@app.post("/api/trace/{performer_id}")
async def update_position(performer_id: str, position: Coordinates, session: DbSession) -> dict:
    performer = session.get(Performer, performer_id)
    if performer is None:
        raise HTTPException(status_code=404, detail="Исполнитель не найден")
    performer.lat = position.lat
    performer.lng = position.lng
    session.commit()
    result = {
        "id": performer.id,
        "name": performer.name,
        "role": performer.role,
        "lat": performer.lat,
        "lng": performer.lng,
        "status": performer.status,
    }
    await events.publish("driverMoved", result)
    return result


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await events.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        events.disconnect(websocket)