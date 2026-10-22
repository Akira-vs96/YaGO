import json
import os
from math import asin, cos, radians, sin, sqrt
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, create_engine, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

app_name = os.getenv("APP_NAME", "YaGo API")
database_url = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://yago:yago@localhost:5432/yago"
)
osrm_base_url = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
osrm_timeout = float(os.getenv("OSRM_TIMEOUT_SECONDS", "5"))
nominatim_base_url = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/")
nominatim_timeout = float(os.getenv("NOMINATIM_TIMEOUT_SECONDS", "8"))
nominatim_user_agent = os.getenv("NOMINATIM_USER_AGENT", "YaGo")
taxi_base_fare = os.getenv("TAXI_BASE_FARE")
taxi_price_per_km = os.getenv("TAXI_PRICE_PER_KM")
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)


class ServiceType(Base):
    __tablename__ = "service_types"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class OrderStatus(Base):
    __tablename__ = "order_statuses"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    service_type_code: Mapped[str] = mapped_column(ForeignKey("service_types.code"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_fare: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    price_per_km: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    price_per_minute: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    address_text: Mapped[str] = mapped_column(String(500), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address_id: Mapped[str] = mapped_column(ForeignKey("addresses.id"), nullable=False)
    cuisine: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    address_ref: Mapped[Address] = relationship()
    menu: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    restaurant_id: Mapped[str] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("menu_categories.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    category_ref: Mapped[MenuCategory] = relationship()
    restaurant: Mapped[Restaurant] = relationship(back_populates="menu")


class Performer(Base):
    __tablename__ = "performers"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    address_id: Mapped[str | None] = mapped_column(ForeignKey("addresses.id"), nullable=True)
    kind: Mapped[str] = mapped_column("type", String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="available")
    user: Mapped[User] = relationship()
    address_ref: Mapped[Address | None] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    service_type_code: Mapped[str] = mapped_column(ForeignKey("service_types.code"), nullable=False)
    restaurant_id: Mapped[str | None] = mapped_column(ForeignKey("restaurants.id"), nullable=True)
    status_code: Mapped[str] = mapped_column(ForeignKey("order_statuses.code"), nullable=False)
    tariff_id: Mapped[str] = mapped_column(ForeignKey("tariffs.id"), nullable=False)
    pickup_address_id: Mapped[str] = mapped_column(ForeignKey("addresses.id"), nullable=False)
    dropoff_address_id: Mapped[str] = mapped_column(ForeignKey("addresses.id"), nullable=False)
    performer_id: Mapped[str | None] = mapped_column(ForeignKey("performers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_ref: Mapped[User] = relationship(foreign_keys=[customer_id])
    service_type: Mapped[ServiceType] = relationship()
    status_ref: Mapped[OrderStatus] = relationship()
    tariff: Mapped[Tariff] = relationship()
    pickup_address: Mapped[Address] = relationship(foreign_keys=[pickup_address_id])
    dropoff_address: Mapped[Address] = relationship(foreign_keys=[dropoff_address_id])
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[str] = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    menu_item: Mapped[MenuItem] = relationship()
    order: Mapped[Order] = relationship(back_populates="items")


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Location(Coordinates):
    address: str = Field(min_length=1, max_length=500)


class OrderLineInput(BaseModel):
    menuItemId: str
    quantity: int = Field(ge=1, le=99)


class CreateOrder(BaseModel):
    customer: str = Field(min_length=1, max_length=120)
    type: Literal["food", "taxi"]
    restaurantId: str | None = None
    items: list[OrderLineInput] = Field(default_factory=list, max_length=50)
    start: Location
    end: Location


class StatusUpdate(BaseModel):
    status: Literal["assigned", "in_progress", "completed", "cancelled"]


def distance_km(start: Coordinates, end: Coordinates) -> float:
    lat1, lat2 = radians(start.lat), radians(end.lat)
    delta_lat = radians(end.lat - start.lat)
    delta_lng = radians(end.lng - start.lng)
    haversine = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lng / 2) ** 2
    return 6371 * 2 * asin(sqrt(haversine))


def ensure_schema() -> None:
    migration_path = os.path.join(os.path.dirname(__file__), "../migrations/001_er_model.sql")
    with open(migration_path, encoding="utf-8") as migration:
        with engine.begin() as connection:
            connection.execute(text(migration.read()))
    Base.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
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
    total = sum(item.quantity * float(item.unit_price) for item in order.items)
    if not order.items:
        total = float(order.tariff.base_fare) + distance_km(
            Coordinates(lat=order.pickup_address.lat, lng=order.pickup_address.lng),
            Coordinates(lat=order.dropoff_address.lat, lng=order.dropoff_address.lng),
        ) * float(order.tariff.price_per_km)
    return {
        "id": order.id,
        "customer": order.customer_ref.full_name,
        "type": order.service_type_code,
        "restaurantId": order.restaurant_id,
        "status": order.status_code,
        "total": round(total),
        "start": {"address": order.pickup_address.address_text, "lat": order.pickup_address.lat, "lng": order.pickup_address.lng},
        "end": {"address": order.dropoff_address.address_text, "lat": order.dropoff_address.lat, "lng": order.dropoff_address.lng},
        "courierId": order.performer_id,
        "createdAt": order.created_at.isoformat(),
        "items": [
            {
                "id": item.menu_item_id,
                "name": item.item_name_snapshot,
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


@app.get("/api/geocode")
async def geocode(
    q: str = Query(min_length=3, max_length=200),
    limit: int = Query(default=5, ge=1, le=10),
) -> list[dict]:
    """Find address points using OpenStreetMap's Nominatim geocoder."""
    query = q if "астан" in q.lower() or "astana" in q.lower() else f"{q}, Астана, Казахстан"
    try:
        async with httpx.AsyncClient(timeout=nominatim_timeout) as client:
            response = await client.get(
                f"{nominatim_base_url}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": limit,
                    "countrycodes": "kz",
                    "accept-language": "ru",
                },
                headers={"User-Agent": nominatim_user_agent},
            )
            response.raise_for_status()
            results = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Сервис поиска адресов временно недоступен",
        ) from error

    return [
        {
            "address": result.get("display_name", ""),
            "lat": float(result["lat"]),
            "lng": float(result["lon"]),
            "type": result.get("type"),
        }
        for result in results
        if result.get("display_name") and result.get("lat") and result.get("lon")
    ]


@app.get("/api/reverse-geocode")
async def reverse_geocode(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
) -> dict:
    """Resolve a map point to a human-readable address."""
    try:
        async with httpx.AsyncClient(timeout=nominatim_timeout) as client:
            response = await client.get(
                f"{nominatim_base_url}/reverse",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "zoom": 18,
                    "accept-language": "ru",
                },
                headers={"User-Agent": nominatim_user_agent},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="Сервис определения адреса временно недоступен",
        ) from error

    address = result.get("display_name")
    if not address:
        raise HTTPException(status_code=404, detail="Для этой точки адрес не найден")
    return {"address": address, "lat": float(result.get("lat", lat)), "lng": float(result.get("lon", lng))}


@app.get("/api/restaurants")
def list_restaurants(session: DbSession) -> list[dict]:
    restaurants = session.scalars(
        select(Restaurant).where(Restaurant.status == "active").order_by(Restaurant.name)
    ).all()
    return [
        {
            "id": restaurant.id,
            "name": restaurant.name,
            "lat": restaurant.address_ref.lat,
            "lng": restaurant.address_ref.lng,
            "address": restaurant.address_ref.address_text,
            "cuisine": restaurant.cuisine,
            "eta": 25,
            "menu": [
                {"id": item.id, "name": item.name, "price": item.price, "category": item.category_ref.name}
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
                    quantity=line.quantity,
                    unit_price=menu_item.price,
                    item_name_snapshot=menu_item.name,
                )
            )
        total = sum(item.quantity * item.unit_price for item in order_items)
    else:
        if body.items:
            raise HTTPException(status_code=422, detail="Корзина еды неприменима к заказу такси")
        restaurant_id = None

    customer = User(
        id=str(uuid4()),
        email=f"{uuid4()}@anonymous.yago",
        full_name=body.customer.strip(),
    )
    start_address = Address(
        id=str(uuid4()), address_text=body.start.address,
        lat=body.start.lat, lng=body.start.lng,
    )
    end_address = Address(
        id=str(uuid4()), address_text=body.end.address,
        lat=body.end.lat, lng=body.end.lng,
    )
    service_type = session.get(ServiceType, body.type)
    tariff = session.scalar(
        select(Tariff).where(Tariff.service_type_code == body.type, Tariff.valid_to.is_(None))
    )
    if service_type is None or tariff is None:
        raise HTTPException(status_code=503, detail="Тариф услуги ещё не настроен оператором")
    order = Order(
        id=str(uuid4()),
        customer_ref=customer,
        service_type=service_type,
        restaurant_id=restaurant_id,
        status_code="pending",
        tariff_id=tariff.id,
        pickup_address=start_address,
        dropoff_address=end_address,
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
    if body.status not in allowed.get(order.status_code, set()):
        raise HTTPException(status_code=409, detail="Недопустимый переход статуса заказа")

    if body.status == "assigned":
        performer_role = "driver" if order.service_type_code == "taxi" else "courier"
        performer = session.scalar(
            select(Performer)
            .where(Performer.kind == performer_role, Performer.status == "available")
            .order_by(Performer.id)
            .with_for_update(skip_locked=True)
        )
        if performer is None:
            raise HTTPException(status_code=409, detail="Нет свободного исполнителя для этого заказа")
        performer.status = "busy"
        order.performer_id = performer.id

    order.status_code = body.status
    if body.status in {"completed", "cancelled"} and order.performer_id:
        performer = session.scalar(
            select(Performer).where(Performer.id == order.performer_id).with_for_update()
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
            "name": person.user.full_name,
            "role": person.kind,
            "lat": person.address_ref.lat if person.address_ref else None,
            "lng": person.address_ref.lng if person.address_ref else None,
            "status": person.status,
        }
        for person in session.scalars(select(Performer).order_by(Performer.id)).all()
    ]


@app.post("/api/trace/{performer_id}")
async def update_position(performer_id: str, position: Coordinates, session: DbSession) -> dict:
    performer = session.get(Performer, performer_id)
    if performer is None:
        raise HTTPException(status_code=404, detail="Исполнитель не найден")
    if performer.address_ref is None:
        performer.address_ref = Address(id=str(uuid4()), address_text="Текущая позиция", lat=position.lat, lng=position.lng)
    else:
        performer.address_ref.lat = position.lat
        performer.address_ref.lng = position.lng
    session.commit()
    result = {
        "id": performer.id,
        "name": performer.user.full_name,
        "role": performer.kind,
        "lat": position.lat,
        "lng": position.lng,
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