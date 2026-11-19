"""Explicit, repeatable demo data for a local YaGo installation."""
import os
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import text

from app.auth import password_hash
from app.db import SessionLocal, migrate


def demo_total(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def seed_example_operations(db):
    """Add repeatable, explicitly fictional examples for several demo customers."""
    tariffs = {row.service_type_code: row for row in db.execute(text("""SELECT DISTINCT ON (service_type_code)
        id,service_type_code,base_fare,price_per_km,price_per_minute FROM tariffs
        WHERE valid_from<=now() AND (valid_to IS NULL OR valid_to>now())
        ORDER BY service_type_code,valid_from DESC,id DESC"""))}
    customer_routes = {
        "client@demo.yago.test": ("Байтерек, Астана", "51.128100", "71.430000",
                                   "Набережная Есиля, Астана", "51.135000", "71.410000"),
        "client2@demo.yago.test": ("ТЦ Хан Шатыр, Астана", "51.132500", "71.403000",
                                    "Ботанический сад, Астана", "51.090300", "71.411800"),
        "student@demo.yago.test": ("Астана Арена, Астана", "51.108300", "71.405400",
                                    "EXPO, Астана", "51.090900", "71.418500"),
        "client3@demo.yago.test": ("Дворец мира и согласия, Астана", "51.123700", "71.470900",
                                    "Вокзал Нұрлы жол, Астана", "51.091700", "71.434700"),
    }
    examples = (
        ("client@demo.yago.test", "driver@demo.yago.test", "taxi", "demo-seed-taxi-001", None, None, 7),
        ("client@demo.yago.test", "courier@demo.yago.test", "food", "demo-seed-food-001", "Зелёный двор", "Бешбармак", 7),
        ("client2@demo.yago.test", "driver2@demo.yago.test", "taxi", "demo-seed-client2-taxi-001", None, None, 6),
        ("client2@demo.yago.test", "courier2@demo.yago.test", "food", "demo-seed-client2-food-001", "Тёплый хлеб", "Сэндвич с курицей", 6),
        ("student@demo.yago.test", "driver3@demo.yago.test", "taxi", "demo-seed-student-taxi-001", None, None, 5),
        ("student@demo.yago.test", "courier@demo.yago.test", "food", "demo-seed-student-food-001", "Лапша и город", "Рамен", 5),
        ("client3@demo.yago.test", "driver@demo.yago.test", "taxi", "demo-seed-client3-taxi-001", None, None, 4),
        ("client3@demo.yago.test", "courier2@demo.yago.test", "food", "demo-seed-client3-food-001", "Зелёный двор", "Баурсаки", 4),
    )
    for customer_email, performer_email, service, key, restaurant_name, item_name, days_ago in examples:
        customer = db.execute(text("SELECT id FROM users WHERE email=:email"),
                              {"email": customer_email}).scalar_one()
        performer = db.execute(text("""SELECT p.id FROM performers p JOIN users u ON u.id=p.user_id
            WHERE u.email=:email"""), {"email": performer_email}).scalar_one()
        if db.execute(text("SELECT 1 FROM orders WHERE customer_id=:customer AND idempotency_key=:key"),
                      {"customer": customer, "key": key}).scalar():
            continue
        restaurant = None
        if service == "food":
            restaurant = db.execute(text("""SELECT r.id,r.name,r.address_id,a.address_text,a.lat,a.lng
                FROM restaurants r JOIN addresses a ON a.id=r.address_id
                WHERE r.name=:name"""), {"name": restaurant_name}).one()
            pickup = restaurant.address_id
            pickup_text, pickup_lat, pickup_lng = restaurant.address_text, restaurant.lat, restaurant.lng
        else:
            pickup_text, pickup_lat, pickup_lng, _, _, _ = customer_routes[customer_email]
            pickup_lat, pickup_lng = Decimal(pickup_lat), Decimal(pickup_lng)
            pickup = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
                VALUES (:text,:lat,:lng) RETURNING id"""),
                {"text": pickup_text, "lat": pickup_lat, "lng": pickup_lng}).scalar_one()
        _, _, _, dropoff_text, dropoff_lat, dropoff_lng = customer_routes[customer_email]
        dropoff_lat, dropoff_lng = Decimal(dropoff_lat), Decimal(dropoff_lng)
        dropoff = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
            VALUES (:text,:lat,:lng) RETURNING id"""),
            {"text": dropoff_text, "lat": dropoff_lat, "lng": dropoff_lng}).scalar_one()
        tariff = tariffs[service]
        delivery = demo_total(tariff.base_fare + tariff.price_per_km * Decimal(2)) if service == "food" else None
        line = db.execute(text("""SELECT id,name,price FROM menu_items
            WHERE restaurant_id=:id AND name=:name"""),
            {"id": restaurant.id, "name": item_name}).one() if restaurant else None
        gross = demo_total(line.price + delivery) if line else demo_total(
            tariff.base_fare + tariff.price_per_km * Decimal(3))
        discount = demo_total(gross * Decimal("0.10")) if customer_email == "student@demo.yago.test" else Decimal("0.00")
        total = demo_total(gross - discount)
        order_id = db.execute(text("""INSERT INTO orders(customer_id,service_type_code,status_code,tariff_id,
            pickup_address_id,dropoff_address_id,restaurant_id,performer_id,created_at,accepted_at,completed_at,
            total_amount,discount_amount,distance_meters,duration_seconds,idempotency_key,pickup_snapshot,dropoff_snapshot,
            pickup_lat_snapshot,pickup_lng_snapshot,dropoff_lat_snapshot,dropoff_lng_snapshot,
            restaurant_name_snapshot,delivery_amount)
            VALUES (:customer,:service,'completed',:tariff,:pickup,:dropoff,:restaurant,:performer,
            now()-(:days * interval '1 day'),now()-(:days * interval '1 day')+interval '5 minutes',
            now()-(:days * interval '1 day')+interval '20 minutes',:total,:discount,:distance,600,:key,:pickup_text,:dropoff_text,
            :pickup_lat,:pickup_lng,:dropoff_lat,:dropoff_lng,:restaurant_name,:delivery) RETURNING id"""),
            {"customer": customer, "service": service, "tariff": tariff.id, "pickup": pickup,
             "dropoff": dropoff, "restaurant": restaurant.id if restaurant else None,
             "performer": performer, "total": total, "discount": discount, "distance": 2000 if line else 3000,
             "days": days_ago,
             "key": key, "pickup_text": pickup_text, "dropoff_text": dropoff_text,
             "pickup_lat": pickup_lat, "pickup_lng": pickup_lng, "dropoff_lat": dropoff_lat,
             "dropoff_lng": dropoff_lng, "restaurant_name": restaurant.name if restaurant else None,
             "delivery": delivery}).scalar_one()
        statuses = (("pending", 0), ("preparing", 1), ("assigned", 3),
                    ("accepted", 5), ("picked_up", 9), ("completed", 20)) if service == "food" else (
                    ("pending", 0), ("assigned", 3), ("accepted", 5),
                    ("arriving", 7), ("in_progress", 10), ("completed", 20))
        for status, minute in statuses:
            db.execute(text("""INSERT INTO order_status_history(order_id,status_code,changed_by_user_id,changed_at)
                VALUES (:order,:status,:actor,now()-(:days * interval '1 day')+(:minute * interval '1 minute'))"""),
                {"order": order_id, "status": status,
                 "actor": customer if status == "pending" else performer,
                 "days": days_ago, "minute": minute})
        if line:
            db.execute(text("""INSERT INTO order_items(order_id,menu_item_id,quantity,unit_price,item_name_snapshot)
                VALUES (:order,:item,1,:price,:name)"""),
                {"order": order_id, "item": line.id, "price": line.price, "name": line.name})
        db.execute(text("INSERT INTO payments(order_id,amount) VALUES (:order,:total)"),
                   {"order": order_id, "total": total})

    scooter_examples = (
        ("client@demo.yago.test", "YG-101", "demo-seed-scooter-001", 51.1290, 71.4290, 7, 8),
        ("client2@demo.yago.test", "YG-102", "demo-seed-client2-scooter-001", 51.1274, 71.4230, 6, 11),
        ("student@demo.yago.test", "YG-103", "demo-seed-student-scooter-001", 51.1310, 71.4340, 5, 6),
        ("client3@demo.yago.test", "YG-104", "demo-seed-client3-scooter-001", 51.1245, 71.4190, 4, 14),
    )
    for customer_email, scooter_code, scooter_key, end_lat, end_lng, days_ago, minutes in scooter_examples:
        customer = db.execute(text("SELECT id FROM users WHERE email=:email"),
                              {"email": customer_email}).scalar_one()
        reservation = db.execute(text("""SELECT id FROM scooter_reservations
            WHERE customer_id=:customer AND idempotency_key=:key"""),
            {"customer": customer, "key": scooter_key}).scalar()
        if reservation:
            continue
        scooter = db.execute(text("SELECT id FROM scooters WHERE code=:code"),
                             {"code": scooter_code}).scalar_one()
        tariff = tariffs["scooter"]
        reservation = db.execute(text("""INSERT INTO scooter_reservations(scooter_id,customer_id,
            tariff_id,status,created_at,expires_at,idempotency_key)
            VALUES (:scooter,:customer,:tariff,'started',now()-(:days * interval '1 day')-interval '5 minutes',
            now()-(:days * interval '1 day')+interval '5 minutes',:key) RETURNING id"""),
            {"scooter": scooter, "customer": customer, "tariff": tariff.id,
             "key": scooter_key, "days": days_ago}).scalar_one()
        total = demo_total(tariff.base_fare + tariff.price_per_minute * Decimal(minutes))
        rental = db.execute(text("""INSERT INTO scooter_rentals(reservation_id,scooter_id,customer_id,
            tariff_id,status,started_at,ended_at,end_lat,end_lng,total_amount)
            VALUES (:reservation,:scooter,:customer,:tariff,'completed',now()-(:days * interval '1 day'),
            now()-(:days * interval '1 day')+(:minutes * interval '1 minute'),:end_lat,:end_lng,:total)
            RETURNING id"""),
            {"reservation": reservation, "scooter": scooter, "customer": customer,
             "tariff": tariff.id, "total": total, "days": days_ago, "minutes": minutes,
             "end_lat": end_lat, "end_lng": end_lng}).scalar_one()
        db.execute(text("""INSERT INTO rental_status_history(rental_id,from_status,to_status,actor_id,changed_at)
            VALUES (:rental,NULL,'active',:customer,now()-(:days * interval '1 day')),
                   (:rental,'active','completed',:customer,now()-(:days * interval '1 day')+
                   (:minutes * interval '1 minute'))"""),
            {"rental": rental, "customer": customer, "days": days_ago, "minutes": minutes})
        db.execute(text("INSERT INTO payments(rental_id,amount) VALUES (:rental,:total)"),
                   {"rental": rental, "total": total})


def seed():
    migrate()
    with SessionLocal.begin() as db:
        people = (
            ("client@demo.yago.test", "Айдана Нур", "client", None),
            ("driver@demo.yago.test", "Данияр Ермек", "driver", "driver"),
            ("courier@demo.yago.test", "Мадина Сагат", "courier", "courier"),
            ("client2@demo.yago.test", "Нурлан Тестов", "client", None),
            ("client3@demo.yago.test", "Алия Тестова", "client", None),
            ("student@demo.yago.test", "Меруерт Студент", "client", None),
            ("driver2@demo.yago.test", "Алихан Садыков", "driver", "driver"),
            ("driver3@demo.yago.test", "Динара Омар", "driver", "driver"),
            ("courier2@demo.yago.test", "Азамат Рахим", "courier", "courier"),
            ("operator@demo.yago.test", "Аружан Серик", "operator", None),
            ("operator2@demo.yago.test", "Сауле Иман", "operator", None),
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
            if email == "student@demo.yago.test":
                db.execute(text("UPDATE users SET student_verified=true WHERE id=:id"), {"id": user_id})

        performer_positions = (
            ("driver@demo.yago.test", 51.1288, 71.4301),
            ("driver2@demo.yago.test", 51.1172, 71.4376),
            ("driver3@demo.yago.test", 51.1381, 71.4140),
            ("courier@demo.yago.test", 51.1255, 71.4192),
            ("courier2@demo.yago.test", 51.1125, 71.4298),
        )
        for email, lat, lng in performer_positions:
            performer = db.execute(text("""SELECT p.id,p.address_id FROM performers p
                JOIN users u ON u.id=p.user_id WHERE u.email=:email"""), {"email": email}).one()
            if not performer.address_id:
                address_id = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
                    VALUES ('Позиция демо-исполнителя',:lat,:lng) RETURNING id"""),
                    {"lat": lat, "lng": lng}).scalar_one()
                db.execute(text("UPDATE performers SET address_id=:address WHERE id=:id"),
                           {"address": address_id, "id": performer.id})

        places = (
            ("Зелёный двор", "Казахская кухня", "проспект Кабанбай батыра, 21", 51.1296, 71.4305,
             (("Бешбармак", "Основное", 2900), ("Баурсаки", "Выпечка", 850), ("Чай с молоком", "Напитки", 650))),
            ("Тёплый хлеб", "Пекарня", "улица Достык, 5", 51.1283, 71.4207,
             (("Сэндвич с курицей", "Основное", 1950), ("Круассан", "Выпечка", 1100), ("Латте", "Напитки", 1200))),
            ("Лапша и город", "Азиатская кухня", "проспект Мәңгілік Ел, 10", 51.1108, 71.4202,
             (("Рамен", "Основное", 3100), ("Гёдза", "Основное", 1800), ("Морс", "Напитки", 750))),
        )
        owners = {
            "Зелёный двор": "operator@demo.yago.test",
            "Тёплый хлеб": "operator2@demo.yago.test",
            "Лапша и город": "operator2@demo.yago.test",
        }
        for name, cuisine, address, lat, lng, menu in places:
            owner_id = db.execute(text("SELECT id FROM users WHERE email=:email"),
                                  {"email": owners[name]}).scalar_one()
            restaurant = db.execute(text("SELECT id,owner_user_id FROM restaurants WHERE name=:name"),
                                    {"name": name}).first()
            if not restaurant:
                address_id = db.execute(text("""INSERT INTO addresses(address_text,lat,lng)
                    VALUES (:address,:lat,:lng) RETURNING id"""),
                    {"address": address, "lat": lat, "lng": lng}).scalar_one()
                restaurant_id = db.execute(text("""INSERT INTO restaurants(owner_user_id,address_id,name,cuisine)
                    VALUES (:owner,:address,:name,:cuisine) RETURNING id"""),
                    {"owner": owner_id, "address": address_id, "name": name, "cuisine": cuisine}).scalar_one()
            else:
                restaurant_id = restaurant.id
                if not restaurant.owner_user_id:
                    db.execute(text("UPDATE restaurants SET owner_user_id=:owner WHERE id=:id"),
                               {"owner": owner_id, "id": restaurant_id})
            for item_name, category_name, price in menu:
                category = db.execute(text("SELECT id FROM menu_categories WHERE name=:name"),
                                      {"name": category_name}).scalar()
                if not category:
                    category = db.execute(text("INSERT INTO menu_categories(name) VALUES (:name) RETURNING id"),
                                          {"name": category_name}).scalar_one()
                db.execute(text("""INSERT INTO menu_items(restaurant_id,category_id,name,price)
                    VALUES (:restaurant,:category,:name,:price) ON CONFLICT (restaurant_id,name) DO NOTHING"""),
                    {"restaurant": restaurant_id, "category": category, "name": item_name, "price": price})

        for code, lat, lng, battery in (("YG-101", 51.1298, 71.4285, 91),
                                         ("YG-102", 51.1277, 71.4230, 76),
                                         ("YG-103", 51.1320, 71.4350, 84),
                                         ("YG-104", 51.1250, 71.4210, 68)):
            db.execute(text("""INSERT INTO scooters(code,qr_code,lat,lng,battery_percent)
                VALUES (:code,:qr,:lat,:lng,:battery) ON CONFLICT (code) DO NOTHING"""),
                {"code": code, "qr": f"YAGO-DEMO-{code}", "lat": lat, "lng": lng, "battery": battery})
        db.execute(text("""INSERT INTO parking_zones(name,boundary,kind)
            VALUES ('Зона обслуживания Астаны',ST_MakeEnvelope(71.37,51.08,71.49,51.18,4326),'service'),
                   ('Центр Астаны',ST_MakeEnvelope(71.39,51.10,71.47,51.16,4326),'parking'),
                   ('Демо-зона запрета',ST_MakeEnvelope(71.44,51.13,71.45,51.14,4326),'no_parking')
            ON CONFLICT (name) DO NOTHING"""))
        demo_events = (
            ("operator@demo.yago.test", "demo_catalog_seeded", "Зелёный двор"),
            ("operator2@demo.yago.test", "demo_catalog_seeded", "Тёплый хлеб"),
            ("operator2@demo.yago.test", "demo_catalog_seeded", "Лапша и город"),
            ("admin@demo.yago.test", "demo_access_review", "Базовые роли и учётные записи"),
        )
        for email, action, subject in demo_events:
            actor = db.execute(text("SELECT id FROM users WHERE email=:email"), {"email": email}).scalar_one()
            exists = db.execute(text("""SELECT 1 FROM audit_events WHERE actor_id=:actor AND action=:action
                AND subject_type='demo_seed' AND subject_id=:subject"""),
                {"actor": actor, "action": action, "subject": subject}).scalar()
            if not exists:
                db.execute(text("""INSERT INTO audit_events(actor_id,action,subject_type,subject_id)
                    VALUES (:actor,:action,'demo_seed',:subject)"""),
                    {"actor": actor, "action": action, "subject": subject})
        seed_example_operations(db)


if __name__ == "__main__":
    seed()
    print("Demo data ready. Credentials: *@demo.yago.test / DEMO_PASSWORD (default YaGo-demo-2026!).")
