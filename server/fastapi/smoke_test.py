"""PostgreSQL/PostGIS integration smoke test. Run only against an isolated demo DB."""
from uuid import uuid4
from decimal import Decimal
import time
from concurrent.futures import ThreadPoolExecutor
import asyncio

from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect
from sqlalchemy import text

from app import events, services
from app.auth import totp
from app.db import SessionLocal
from app.main import app


async def fixed_route(start, end):
    return {"distance": 2500, "duration": 600, "geometry": {
        "type": "LineString", "coordinates": [[start.lng, start.lat], [end.lng, end.lat]]}}


services.driving_route = fixed_route
point_a = {"address": "Точка А, Астана", "lat": 51.128, "lng": 71.421}
point_b = {"address": "Точка Б, Астана", "lat": 51.132, "lng": 71.431}
password = "Integration-2026!"


def request(client, method, path, payload=None, key=None):
    headers = {"X-CSRF-Token": client.cookies.get("yago_csrf", "")}
    if key:
        headers["Idempotency-Key"] = key
    return client.request(method, path, json=payload, headers=headers)


def check(response, expected):
    assert response.status_code == expected, f"{response.status_code} {response.text}"
    return response.json()


class FakeSocket:
    def __init__(self):
        self.messages = []

    async def send_text(self, message):
        self.messages.append(message)


with TestClient(app) as customer, TestClient(app) as other, TestClient(app) as operator, \
     TestClient(app) as driver, TestClient(app) as courier, TestClient(app) as admin:
    suffix = uuid4().hex[:10]
    check(request(customer, "POST", "/api/auth/register",
                  {"email": f"client-{suffix}@test.yago.local", "password": password, "full_name": "Клиент Один"}), 201)
    check(request(other, "POST", "/api/auth/register",
                  {"email": f"other-{suffix}@test.yago.local", "password": password, "full_name": "Клиент Два"}), 201)
    assert check(request(customer, "GET", "/api/auth/me"), 200)["roles"] == ["client"]
    check(request(operator, "POST", "/api/auth/login",
                  {"email": "operator@demo.yago.test", "password": "YaGo-demo-2026!"}), 200)
    check(request(driver, "POST", "/api/auth/login",
                  {"email": "driver@demo.yago.test", "password": "YaGo-demo-2026!"}), 200)
    check(request(courier, "POST", "/api/auth/login",
                  {"email": "courier@demo.yago.test", "password": "YaGo-demo-2026!"}), 200)
    check(request(admin, "POST", "/api/auth/login",
                  {"email": "admin@demo.yago.test", "password": "YaGo-demo-2026!"}), 200)
    assert request(other, "POST", "/api/auth/login",
                   {"email": "other-nonexistent@test.yago.local", "password": password}).status_code == 401
    assert any(event["action"] == "login_failed" for event in
               check(request(admin, "GET", "/api/admin/audit"), 200))
    assert any(event["action"] == "login_failed" for event in
               check(request(admin, "GET", "/api/admin/login-events"), 200))
    assert request(customer, "GET", "/api/admin/login-events").status_code == 403
    assert request(customer, "PATCH", "/api/profile", {"fullName": "Новый клиент"}).status_code == 200
    assert customer.patch("/api/profile", json={"fullName": "Без CSRF"}).status_code == 403
    assert request(customer, "PATCH", "/api/admin/users/00000000-0000-0000-0000-000000000000/role",
                   {"role": "admin", "enabled": True}).status_code == 403
    with SessionLocal.begin() as db:
        demo_driver = db.scalar(text("""SELECT p.id FROM performers p JOIN users u ON u.id=p.user_id
            WHERE u.email='driver@demo.yago.test'"""))
        near = db.scalar(text("""INSERT INTO addresses(address_text,lat,lng)
            VALUES ('Точка рядом',51.128,71.421) RETURNING id"""))
        db.execute(text("UPDATE performers SET address_id=:address,status='available' WHERE id=:id"),
                   {"address": near, "id": demo_driver})
        far_user = db.scalar(text("""INSERT INTO users(email,full_name)
            VALUES (:email,'Дальний водитель') RETURNING id"""),
            {"email": f"far-driver-{suffix}@test.yago.local"})
        far = db.scalar(text("""INSERT INTO addresses(address_text,lat,lng)
            VALUES ('Дальняя точка',51.300,71.600) RETURNING id"""))
        far_id = f"00000000-0000-0000-0000-{suffix.zfill(12)}"
        db.execute(text("""INSERT INTO performers(id,user_id,address_id,type,status)
            VALUES (:id,:user,:address,'driver','available')"""),
            {"id": far_id, "user": far_user, "address": far})
    assert request(customer, "POST", "/api/auth/student/verify", {"code": "wrong"}).status_code == 422
    check(request(customer, "POST", "/api/auth/student/verify", {"code": "YAGO-STUDENT"}), 200)

    taxi = {"type": "taxi", "start": point_a, "end": point_b}
    quote = check(request(customer, "POST", "/api/quotes", taxi), 200)
    standard_quote = check(request(other, "POST", "/api/quotes", taxi), 200)
    assert Decimal(quote["discount"]) > 0
    assert Decimal(quote["total"]) + Decimal(quote["discount"]) == Decimal(standard_quote["total"])
    order_data = {**taxi, "quotedTotal": quote["total"], "tariffId": quote["tariffId"]}
    key = str(uuid4())
    assert request(customer, "POST", "/api/orders", {**order_data, "quotedTotal": "1"}, key).status_code == 409
    order = check(request(customer, "POST", "/api/orders", order_data, key), 201)
    assert order["routeGeometry"]["coordinates"] == [[point_a["lng"], point_a["lat"]],
                                                   [point_b["lng"], point_b["lat"]]]
    assert check(request(customer, "POST", "/api/orders", order_data, key), 201)["id"] == order["id"]
    assert request(customer, "POST", "/api/orders", {**order_data, "end": point_a}, key).status_code == 409
    assert request(other, "GET", f"/api/orders/{order['id']}").status_code == 404
    assert request(other, "PATCH", f"/api/orders/{order['id']}/status", {"status": "cancelled"}).status_code == 409
    assert request(customer, "PATCH", f"/api/orders/{order['id']}/status", {"status": "completed"}).status_code == 409
    assigned = check(request(operator, "PATCH", f"/api/orders/{order['id']}/status", {"status": "assigned"}), 200)
    assert assigned["performerId"] == str(demo_driver)
    for state in ("accepted", "arriving", "in_progress", "completed"):
        check(request(driver, "PATCH", f"/api/orders/{order['id']}/status", {"status": state}), 200)
        if state == "accepted":
            performer_id = check(request(driver, "GET", f"/api/orders/{order['id']}"), 200)["performerId"]
            assert request(other, "POST", f"/api/trace/{performer_id}",
                           {"lat": 51.13, "lng": 71.42}).status_code == 404
            check(request(driver, "POST", f"/api/trace/{performer_id}",
                          {"lat": 51.13, "lng": 71.42}), 200)
            assert check(request(customer, "GET", f"/api/orders/{order['id']}"), 200)["performerPosition"]["lat"] == 51.13
            identities = [check(request(client, "GET", "/api/auth/me"), 200)
                          for client in (customer, other, driver, admin)]
            sockets = [FakeSocket() for _ in identities]
            events.connections.update(zip(sockets, identities))
            try:
                asyncio.run(events.publish("orderStatusUpdated",
                                           check(request(customer, "GET", f"/api/orders/{order['id']}"), 200)))
                assert [bool(socket.messages) for socket in sockets] == [True, False, True, True]
            finally:
                for socket in sockets:
                    events.connections.pop(socket, None)
    assert check(request(customer, "GET", f"/api/orders/{order['id']}"), 200)["performerPosition"] is None
    assert request(driver, "PATCH", f"/api/orders/{order['id']}/status", {"status": "completed"}).status_code == 409
    check(request(customer, "POST", f"/api/orders/{order['id']}/review", {"rating": 5}), 201)
    assert request(customer, "POST", f"/api/orders/{order['id']}/review", {"rating": 4}).status_code == 409

    restaurants = check(request(customer, "GET", "/api/restaurants"), 200)
    place = restaurants[0]
    item = place["menu"][0]
    food = {"type": "food", "restaurantId": place["id"], "items": [{"menuItemId": item["id"], "quantity": 2}], "end": point_b}
    food_quote = check(request(customer, "POST", "/api/quotes", food), 200)
    food_order = check(request(customer, "POST", "/api/orders",
                               {**food, "quotedTotal": food_quote["total"], "tariffId": food_quote["tariffId"]},
                               str(uuid4())), 201)
    assert food_order["items"][0]["unitPrice"] == item["price"]
    check(request(operator, "PATCH", f"/api/orders/{food_order['id']}/status", {"status": "preparing"}), 200)
    check(request(operator, "PATCH", f"/api/orders/{food_order['id']}/status", {"status": "assigned"}), 200)
    for state in ("accepted", "picked_up", "completed"):
        check(request(courier, "PATCH", f"/api/orders/{food_order['id']}/status", {"status": state}), 200)
    check(request(operator, "PATCH", f"/api/operator/menu/{item['id']}",
                  {"name": item["name"], "category": item["category"], "price": "9999",
                   "description": "", "available": True}), 200)
    assert check(request(customer, "GET", f"/api/orders/{food_order['id']}"), 200)["items"][0]["unitPrice"] == item["price"]
    with SessionLocal() as db:
        db.execute(text("UPDATE restaurants SET name='Временное название' WHERE id=:id"), {"id": place["id"]})
        assert services.order_view(db, food_order["id"])["restaurant"] == place["name"]
        db.rollback()
    with SessionLocal() as db:
        pickup_id = db.scalar(text("SELECT pickup_address_id FROM orders WHERE id=:id"), {"id": order["id"]})
        db.execute(text("UPDATE addresses SET address_text='Адрес изменён',lat=51.5 WHERE id=:id"),
                   {"id": pickup_id})
        archived = services.order_view(db, order["id"])
        assert archived["start"]["address"] == point_a["address"]
        assert archived["start"]["lat"] == point_a["lat"]
        assert not any(float(cell["lat"]) == 51.5 for cell in
                       services.heatmap({"roles": ["admin"]}, db, limit=100))
        db.rollback()
    with SessionLocal() as db:
        try:
            db.execute(text("UPDATE tariffs SET base_fare=1 WHERE id=:id"), {"id": quote["tariffId"]})
        except Exception:
            db.rollback()
        else:
            raise AssertionError("Used tariff was mutated")

    scooter = check(request(customer, "GET", "/api/scooters"), 200)[0]
    reservation = check(request(customer, "POST", "/api/scooters/reserve",
                                {"scooterId": scooter["id"]}, str(uuid4())), 201)
    assert request(other, "POST", "/api/scooters/reserve", {"scooterId": scooter["id"]}, str(uuid4())).status_code == 409
    qr = check(request(customer, "GET", f"/api/reservations/{reservation['id']}/demo-qr"), 200)["qrCode"]
    rental = check(request(customer, "POST", f"/api/reservations/{reservation['id']}/start", {"qrCode": qr}), 200)
    old_rate = rental["tariff"]
    new_rate = check(request(operator, "POST", "/api/operator/tariffs",
        {"service": "scooter", "name": f"Новая версия {suffix}", "baseFare": "999",
         "pricePerKm": "0", "pricePerMinute": "999"}), 201)
    assert check(request(customer, "POST", f"/api/reservations/{reservation['id']}/start", {"qrCode": qr}), 200)["id"] == rental["id"]
    assert request(other, "POST", f"/api/rentals/{rental['id']}/finish", point_a).status_code == 404
    assert request(customer, "POST", f"/api/rentals/{rental['id']}/finish", {"lat": 50.0, "lng": 70.0}).status_code == 409
    finished = check(request(customer, "POST", f"/api/rentals/{rental['id']}/finish", point_a), 200)
    assert finished["status"] == "completed"
    expected_total = Decimal(old_rate["baseFare"]) + Decimal(old_rate["pricePerMinute"])
    assert Decimal(finished["total"]) == expected_total
    assert finished["tariff"]["id"] == old_rate["id"]
    assert request(customer, "DELETE", f"/api/operator/tariffs/{new_rate['id']}").status_code == 403
    check(request(operator, "PATCH", f"/api/operator/tariffs/{new_rate['id']}",
        {"service": "scooter", "name": f"Исправленная версия {suffix}", "baseFare": "998",
         "pricePerKm": "0", "pricePerMinute": "998"}), 200)
    assert any(t["id"] == new_rate["id"] for t in check(request(operator, "GET", "/api/operator/tariffs"), 200))
    check(request(operator, "DELETE", f"/api/operator/tariffs/{new_rate['id']}"), 200)
    assert request(operator, "PATCH", f"/api/operator/tariffs/{old_rate['id']}",
        {"service": "scooter", "name": "Нельзя менять", "baseFare": "1",
         "pricePerKm": "0", "pricePerMinute": "1"}).status_code == 409
    assert check(request(customer, "POST", f"/api/rentals/{rental['id']}/finish", point_a), 200)["total"] == finished["total"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        races = list(pool.map(lambda args: request(args[0], "POST", "/api/scooters/reserve",
                                                  {"scooterId": scooter["id"]}, str(uuid4())),
                              [(customer,), (other,)]))
    assert sorted(r.status_code for r in races) == [201, 409], [r.text for r in races]
    winning_reservation = next(r.json() for r in races if r.status_code == 201)
    with SessionLocal.begin() as db:
        db.execute(text("""UPDATE scooter_reservations SET created_at=now()-interval '20 minutes',
            expires_at=now()-interval '1 minute' WHERE id=:id"""), {"id": winning_reservation["id"]})
    check(request(customer, "GET", "/api/scooters"), 200)
    with SessionLocal() as db:
        assert db.scalar(text("SELECT status FROM scooter_reservations WHERE id=:id"),
                         {"id": winning_reservation["id"]}) == "expired"
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM payments WHERE rental_id=:id"), {"id": rental["id"]}) == 1
        assert db.scalar(text("SELECT count(*) FROM payments WHERE order_id=:id"), {"id": order["id"]}) == 1
        db.execute(text("INSERT INTO service_types(code,name,active) VALUES ('bike','Исторический велосипед',false) ON CONFLICT DO NOTHING"))
        try:
            db.execute(text("""INSERT INTO orders(customer_id,service_type_code,status_code,tariff_id,
                pickup_address_id,dropoff_address_id)
                SELECT customer_id,'bike','pending',tariff_id,pickup_address_id,dropoff_address_id
                FROM orders WHERE id=:id"""), {"id": order["id"]})
        except Exception:
            db.rollback()
        else:
            raise AssertionError("Inactive bicycle type accepted")
    zone_name = f"Тестовая зона {suffix}"
    zone = check(request(operator, "POST", "/api/operator/zones",
                         {"name": zone_name, "south": 51.10, "north": 51.11,
                          "west": 71.40, "east": 71.41}), 201)
    assert any(z["id"] == zone["id"] for z in check(request(operator, "GET", "/api/operator/zones"), 200))
    check(request(operator, "PATCH", f"/api/operator/zones/{zone['id']}",
        {"name": f"Исправленная зона {suffix}", "south": 51.10, "north": 51.11,
         "west": 71.40, "east": 71.41, "active": False}), 200)
    assert any(z["name"] == f"Исправленная зона {suffix}" for z in
               check(request(operator, "GET", "/api/operator/zones"), 200))
    assert request(customer, "DELETE", f"/api/operator/zones/{zone['id']}").status_code == 403
    check(request(operator, "DELETE", f"/api/operator/zones/{zone['id']}"), 200)
    restaurant = check(request(operator, "POST", "/api/operator/restaurants",
                               {"name": f"Тестовое кафе {suffix}", "cuisine": "Учебная", "address": point_a}), 201)
    check(request(operator, "PATCH", f"/api/operator/restaurants/{restaurant['id']}/status",
                  {"active": False}), 200)
    vehicle = check(request(operator, "POST", "/api/operator/scooters",
                            {"code": f"TEST-{suffix}", "qrCode": f"QR-{suffix}",
                             "lat": 51.13, "lng": 71.43, "battery": 90}), 201)
    check(request(operator, "PATCH", f"/api/operator/scooters/{vehicle['id']}",
                  {"status": "maintenance", "battery": 90}), 200)
    assert check(request(admin, "GET", "/api/admin/analytics"), 200)["orders"] >= 2
    assert request(admin, "GET", "/api/admin/analytics?from_at=2027-01-01T00:00:00Z&to_at=2027-02-01T00:00:00Z").status_code == 200
    assert check(request(admin, "GET", "/api/admin/heatmap"), 200)
    other_id = check(request(other, "GET", "/api/auth/me"), 200)["id"]
    assert check(request(admin, "GET", f"/api/admin/users/{other_id}/sessions"), 200)
    setup = check(request(other, "POST", "/api/auth/2fa/setup"), 200)
    code = totp(setup["secret"], int(time.time() // 30))
    check(request(other, "POST", "/api/auth/2fa/enable", {"code": code}), 200)
    check(request(other, "POST", "/api/auth/logout"), 200)
    assert check(request(other, "POST", "/api/auth/login",
                         {"email": f"other-{suffix}@test.yago.local", "password": password}), 200)["requires2fa"]
    assert request(other, "GET", "/api/auth/me").status_code == 401
    check(request(other, "POST", "/api/auth/verify-2fa", {"code": code}), 200)
    assert request(other, "GET", "/api/auth/me").status_code == 200
    check(request(customer, "POST", "/api/auth/logout"), 200)
    assert request(customer, "GET", "/api/auth/me").status_code == 401
with TestClient(app) as anonymous:
    try:
        with anonymous.websocket_connect("/ws") as socket:
            socket.receive_text()
    except WebSocketDisconnect as exc:
        assert exc.code == 4401
    else:
        raise AssertionError("Unauthenticated WebSocket accepted")

print("Integration smoke: auth, roles, taxi, food, scooter, idempotency, PostGIS and archive guard OK")
