"""Explicit, repeatable demo data for a local YaGo installation."""
import os
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import text

from app.auth import password_hash
from app.db import SessionLocal, migrate


def demo_total(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def seed_example_operations(db):
    """Add one historical, explicitly fictional example of each service."""
    customer = db.execute(text("SELECT id FROM users WHERE email='client@demo.yago.test'")).scalar_one()
    driver = db.execute(text("""SELECT p.id FROM performers p JOIN users u ON u.id=p.user_id
        WHERE u.email='driver@demo.yago.test'""")).scalar_one()
    courier = db.execute(text("""SELECT p.id FROM performers p JOIN users u ON u.id=p.user_id
        WHERE u.email='courier@demo.yago.test'""")).scalar_one()
    tariffs = {row.service_type_code: row for row in db.execute(text("""SELECT DISTINCT ON (service_type_code)
        id,service_type_code,base_fare,price_per_km,price_per_minute FROM tariffs
        WHERE valid_from<=now() AND (valid_to IS NULL OR valid_to>now())
        ORDER BY service_type_code,valid_from DESC,id DESC"""))}
    for service, performer, key in (("taxi", driver, "demo-seed-taxi-001"),
                                    ("food", courier, "demo-seed-food-001")):
        if db.execute(text("SELECT 1 FROM orders WHERE customer_id=:customer AND idempotency_key=:key"),
                      {"customer": customer, "key": key}).scalar():
            continue
        restaurant = None
        if service == "food":
            restaurant = db.execute(text("""SELECT r.id,r.name,r.address_id,a.address_text,a.lat,a.lng
                FROM restaurants r JOIN addresses a ON a.id=r.address_id
                WHERE r.name='Зелёный двор'""")).one()
            pickup = restaurant.address_id
            pickup_text, pickup_lat, pickup_lng = restaurant.address_text, restaurant.lat, restaurant.lng
        else:
            pickup_text, pickup_lat, pickup_lng = "Байтерек, Астана", Decimal("51.128100"), Decimal("71.430000")
            pickup = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
                VALUES (:text,:lat,:lng) RETURNING id"""),
                {"text": pickup_text, "lat": pickup_lat, "lng": pickup_lng}).scalar_one()
        dropoff_text, dropoff_lat, dropoff_lng = "Набережная Есиля, Астана", Decimal("51.135000"), Decimal("71.410000")
        dropoff = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
            VALUES (:text,:lat,:lng) RETURNING id"""),
            {"text": dropoff_text, "lat": dropoff_lat, "lng": dropoff_lng}).scalar_one()
        tariff = tariffs[service]
        delivery = demo_total(tariff.base_fare + tariff.price_per_km * Decimal(2)) if service == "food" else None
        line = db.execute(text("""SELECT id,name,price FROM menu_items
            WHERE restaurant_id=:id AND name='Бешбармак'"""), {"id": restaurant.id}).one() if restaurant else None
        total = demo_total(line.price + delivery) if line else demo_total(
            tariff.base_fare + tariff.price_per_km * Decimal(3))
        order_id = db.execute(text("""INSERT INTO orders(customer_id,service_type_code,status_code,tariff_id,
            pickup_address_id,dropoff_address_id,restaurant_id,performer_id,created_at,accepted_at,completed_at,
            total_amount,distance_meters,duration_seconds,idempotency_key,pickup_snapshot,dropoff_snapshot,
            pickup_lat_snapshot,pickup_lng_snapshot,dropoff_lat_snapshot,dropoff_lng_snapshot,
            restaurant_name_snapshot,delivery_amount)
            VALUES (:customer,:service,'completed',:tariff,:pickup,:dropoff,:restaurant,:performer,
            now()-interval '3 days',now()-interval '3 days'+interval '5 minutes',
            now()-interval '3 days'+interval '20 minutes',:total,:distance,600,:key,:pickup_text,:dropoff_text,
            :pickup_lat,:pickup_lng,:dropoff_lat,:dropoff_lng,:restaurant_name,:delivery) RETURNING id"""),
            {"customer": customer, "service": service, "tariff": tariff.id, "pickup": pickup,
             "dropoff": dropoff, "restaurant": restaurant.id if restaurant else None,
             "performer": performer, "total": total, "distance": 2000 if line else 3000,
             "key": key, "pickup_text": pickup_text, "dropoff_text": dropoff_text,
             "pickup_lat": pickup_lat, "pickup_lng": pickup_lng, "dropoff_lat": dropoff_lat,
             "dropoff_lng": dropoff_lng, "restaurant_name": restaurant.name if restaurant else None,
             "delivery": delivery}).scalar_one()
        if line:
            db.execute(text("""INSERT INTO order_items(order_id,menu_item_id,quantity,unit_price,item_name_snapshot)
                VALUES (:order,:item,1,:price,:name)"""),
                {"order": order_id, "item": line.id, "price": line.price, "name": line.name})
        db.execute(text("INSERT INTO payments(order_id,amount) VALUES (:order,:total)"),
                   {"order": order_id, "total": total})

    scooter_key = "demo-seed-scooter-001"
    reservation = db.execute(text("""SELECT id FROM scooter_reservations
        WHERE customer_id=:customer AND idempotency_key=:key"""),
        {"customer": customer, "key": scooter_key}).scalar()
    if not reservation:
        scooter = db.execute(text("SELECT id FROM scooters WHERE code='YG-101'")).scalar_one()
        reservation = db.execute(text("""INSERT INTO scooter_reservations(scooter_id,customer_id,status,
            created_at,expires_at,idempotency_key) VALUES (:scooter,:customer,'started',
            now()-interval '3 days'-interval '5 minutes',now()-interval '3 days'+interval '5 minutes',:key)
            RETURNING id"""), {"scooter": scooter, "customer": customer, "key": scooter_key}).scalar_one()
        tariff = tariffs["scooter"]
        total = demo_total(tariff.base_fare + tariff.price_per_minute * Decimal(8))
        rental = db.execute(text("""INSERT INTO scooter_rentals(reservation_id,scooter_id,customer_id,
            tariff_id,status,started_at,ended_at,end_lat,end_lng,total_amount)
            VALUES (:reservation,:scooter,:customer,:tariff,'completed',now()-interval '3 days',
            now()-interval '3 days'+interval '8 minutes',51.129000,71.429000,:total) RETURNING id"""),
            {"reservation": reservation, "scooter": scooter, "customer": customer,
             "tariff": tariff.id, "total": total}).scalar_one()
        db.execute(text("INSERT INTO payments(rental_id,amount) VALUES (:rental,:total)"),
                   {"rental": rental, "total": total})


def seed():
    migrate()
    with SessionLocal.begin() as db:
        people = (
            ("client@demo.yago.test", "Айдана Нур", "client", None),
            ("driver@demo.yago.test", "Данияр Ермек", "driver", "driver"),
            ("courier@demo.yago.test", "Мадина Сагат", "courier", "courier"),
            ("operator@demo.yago.test", "Аружан Серик", "operator", None),
            ("admin@demo.yago.test", "Тимур Асан", "admin", None),
        )
        password = os.getenv("DEMO_PASSWORD", "YaGo-demo-2026!")
        for email, name, role, performer_type in people:
            user_id = db.execute(text("""INSERT INTO users(email,full_name,password_hash)
                VALUES (:email,:name,:password) ON CONFLICT (email) DO UPDATE SET email=EXCLUDED.email
                RETURNING id"""), {"email": email, "name": name, "password": password_hash(password)}).scalar_one()
            db.execute(text("INSERT INTO user_roles(user_id,role_code) VALUES (:id,:role) ON CONFLICT DO NOTHING"),
                       {"id": user_id, "role": role})
            if performer_type:
                db.execute(text("""INSERT INTO performers(user_id,type) VALUES (:id,:type)
                    ON CONFLICT (user_id) DO NOTHING"""), {"id": user_id, "type": performer_type})

        places = (
            ("Зелёный двор", "Казахская кухня", "проспект Кабанбай батыра, 21", 51.1296, 71.4305,
             (("Бешбармак", "Основное", 2900), ("Баурсаки", "Выпечка", 850), ("Чай с молоком", "Напитки", 650))),
            ("Тёплый хлеб", "Пекарня", "улица Достык, 5", 51.1283, 71.4207,
             (("Сэндвич с курицей", "Основное", 1950), ("Круассан", "Выпечка", 1100), ("Латте", "Напитки", 1200))),
            ("Лапша и город", "Азиатская кухня", "проспект Мәңгілік Ел, 10", 51.1108, 71.4202,
             (("Рамен", "Основное", 3100), ("Гёдза", "Основное", 1800), ("Морс", "Напитки", 750))),
        )
        for name, cuisine, address, lat, lng, menu in places:
            restaurant = db.execute(text("SELECT id FROM restaurants WHERE name=:name"), {"name": name}).scalar()
            if not restaurant:
                address_id = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
                    VALUES (:address,:lat,:lng) RETURNING id"""),
                    {"address": address, "lat": lat, "lng": lng}).scalar_one()
                restaurant = db.execute(text("""INSERT INTO restaurants(address_id,name,cuisine)
                    VALUES (:address,:name,:cuisine) RETURNING id"""),
                    {"address": address_id, "name": name, "cuisine": cuisine}).scalar_one()
            for item_name, category_name, price in menu:
                category = db.execute(text("SELECT id FROM menu_categories WHERE name=:name"),
                                      {"name": category_name}).scalar()
                if not category:
                    category = db.execute(text("INSERT INTO menu_categories(name) VALUES (:name) RETURNING id"),
                                          {"name": category_name}).scalar_one()
                db.execute(text("""INSERT INTO menu_items(restaurant_id,category_id,name,price)
                    VALUES (:restaurant,:category,:name,:price) ON CONFLICT (restaurant_id,name) DO NOTHING"""),
                    {"restaurant": restaurant, "category": category, "name": item_name, "price": price})

        for code, lat, lng, battery in (("YG-101", 51.1298, 71.4285, 91),
                                         ("YG-102", 51.1277, 71.4230, 76),
                                         ("YG-103", 51.1320, 71.4350, 84)):
            db.execute(text("""INSERT INTO scooters(code,qr_code,lat,lng,battery_percent)
                VALUES (:code,:qr,:lat,:lng,:battery) ON CONFLICT (code) DO NOTHING"""),
                {"code": code, "qr": f"YAGO-DEMO-{code}", "lat": lat, "lng": lng, "battery": battery})
        db.execute(text("""INSERT INTO parking_zones(name,boundary)
            VALUES ('Центр Астаны',ST_MakeEnvelope(71.39,51.10,71.47,51.16,4326))
            ON CONFLICT (name) DO NOTHING"""))
        seed_example_operations(db)


if __name__ == "__main__":
    seed()
    print("Demo data ready. Credentials: *@demo.yago.test / DEMO_PASSWORD (default YaGo-demo-2026!).")
