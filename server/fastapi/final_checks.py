"""Additional team acceptance checks, called from smoke_test.py on a disposable database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from time import monotonic
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text

from app import maps, services
from app.db import SessionLocal


def simultaneous(*calls):
    barrier = Barrier(len(calls), timeout=10)

    def run(call):
        barrier.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def check_access(request, check, client, operator, admin, suffix):
    credentials = {"email": f"limit-{suffix}@test.yago.local", "password": "WrongPassword123"}
    for _ in range(5):
        check(request(client, "POST", "/api/auth/login", credentials), 401)
    check(request(client, "POST", "/api/auth/login", credentials), 429)
    log = check(request(admin, "GET", "/api/admin/login-events"), 200)
    assert any(row["action"] == "login_rate_limited" for row in log)
    for account in (client, operator):
        check(request(account, "GET", "/api/admin/analytics"), 403)
    assert check(request(client, "GET", "/api/auth/sessions"), 200)


def check_orders(request, check, customer, operator, taxi):
    def book():
        quote = check(request(customer, "POST", "/api/quotes", taxi), 200)
        data = {**taxi, "quotedTotal": quote["total"], "tariffId": quote["tariffId"]}
        return check(request(customer, "POST", "/api/orders", data, str(uuid4())), 201)

    with SessionLocal() as db:
        free = db.scalar(text("SELECT count(*) FROM performers WHERE type='driver' AND status='available'"))
    assert free >= 2
    waiting = [book() for _ in range(free)]
    quote = check(request(customer, "POST", "/api/quotes", taxi), 200)
    assert Decimal(quote["surgeMultiplier"]) == Decimal("1.25")
    with SessionLocal() as db:
        tariff = services.active_tariff(db, "taxi")
    gross = services.amount((tariff["base_fare"] + tariff["price_per_km"] * Decimal("2.5")) * Decimal("1.25"))
    assert Decimal(quote["total"]) == gross - services.amount(gross * Decimal("0.10"))
    key = str(uuid4())
    data = {**taxi, "quotedTotal": quote["total"], "tariffId": quote["tariffId"]}
    create = lambda: request(customer, "POST", "/api/orders", data, key)
    copies = [check(response, 201) for response in simultaneous(create, create)]
    assert copies[0]["id"] == copies[1]["id"]
    assert Decimal(copies[0]["surgeMultiplier"]) == Decimal("1.25")

    def assign(order):
        return request(operator, "PATCH", f"/api/orders/{order['id']}/status", {"status": "assigned"})

    assigned = simultaneous(lambda: assign(waiting[0]), lambda: assign(waiting[1]))
    assert len({check(response, 200)["performerId"] for response in assigned}) == 2
    for order in [*waiting, copies[0]]:
        check(request(customer, "PATCH", f"/api/orders/{order['id']}/status", {"status": "cancelled"}), 200)
    assert Decimal(check(request(customer, "POST", "/api/quotes", taxi), 200)["surgeMultiplier"]) == 1


def check_fleet(request, check, client, operator, vehicle, parking):
    key = vehicle["id"]
    path = f"/api/operator/scooters/{key}"

    def change(status):
        return request(operator, "PATCH", path, {"status": status, "battery": 90})

    def book():
        return request(client, "POST", "/api/scooters/reserve", {"scooterId": key}, str(uuid4()))

    for state in ("maintenance", "blocked"):
        check(change(state), 200)
        check(book(), 409)
    check(change("available"), 200)
    reserved, blocked = simultaneous(book, lambda: change("blocked"))
    assert (reserved.status_code, blocked.status_code) in ((201, 409), (409, 200))
    if blocked.status_code == 200:
        check(change("available"), 200)
        reserved = book()
    start = f"/api/reservations/{check(reserved, 201)['id']}"
    check(change("maintenance"), 409)
    qr = check(request(client, "GET", start + "/demo-qr"), 200)
    begin = lambda: request(client, "POST", start + "/start", {"qrCode": qr["qrCode"]})
    a, b = [check(r, 200) for r in simultaneous(begin, begin)]
    assert a["id"] == b["id"]
    check(change("blocked"), 409)
    finish = lambda: request(client, "POST", f"/api/rentals/{a['id']}/finish", parking)
    a, b = [check(r, 200) for r in simultaneous(finish, finish)]
    assert a["status"] == b["status"] == "completed" and a["total"] == b["total"]
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM payments WHERE rental_id=:id"), {"id": a["id"]}) == 1
    reservation = check(book(), 201)
    with SessionLocal.begin() as db:
        db.execute(text("""UPDATE scooter_reservations SET created_at=now()-interval '20 minutes',
            expires_at=now()-interval '1 minute' WHERE id=:id"""), {"id": reservation["id"]})
    check(change("maintenance"), 200)
    check(change("available"), 200)


async def check_provider_timeout():
    with patch.object(httpx.AsyncClient, "get", new=AsyncMock(side_effect=httpx.ReadTimeout("fixture"))):
        start = services.Point(address="Старт", lat=51.11, lng=71.44)
        end = services.Point(address="Финиш", lat=51.12, lng=71.46)
        for call in (maps.nominatim("/search", {"q": "timeout-fixture"}), REAL_ROUTE(start, end)):
            try:
                await call
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("Provider timeout was not reported")


REAL_ROUTE = services.driving_route


def check_analytics_volume():
    admin = {"roles": ["admin"]}
    with SessionLocal() as db:
        before = services.analytics(admin, db)
        db.execute(text("""INSERT INTO orders(customer_id,service_type_code,status_code,tariff_id,
            pickup_address_id,dropoff_address_id,total_amount)
            SELECT o.customer_id,'taxi','pending',o.tariff_id,o.pickup_address_id,o.dropoff_address_id,1000
            FROM (SELECT * FROM orders WHERE service_type_code='taxi' LIMIT 1) o
            CROSS JOIN generate_series(1,10000)"""))
        started = monotonic()
        after = services.analytics(admin, db)
        assert after["orders"] - before["orders"] == 10000 and after["revenue"] == before["revenue"]
        assert max(cell["count"] for cell in services.heatmap(admin, db, limit=100)) >= 10000
        print(f"Analytics and heatmap: 10000 extra orders, {(monotonic()-started)*1000:.0f} ms; rolled back.")
