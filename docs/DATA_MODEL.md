# Данные, связи и исторические факты

```mermaid
erDiagram
  users ||--o{ user_roles : has
  roles ||--o{ user_roles : assigns
  users ||--o{ sessions : opens
  users ||--o{ login_challenges : confirms
  users o|--o{ addresses : saves
  users o|--o{ restaurants : owns
  users o|--o{ order_status_history : records
  users o|--o{ rental_status_history : records
  users ||--o{ scooter_rentals : rides
  users ||--o{ orders : creates
  users ||--o| performers : represents
  users o|--o{ audit_events : initiates
  users ||--o{ reviews : writes
  addresses o|--o{ performers : last_position
  users ||--o{ scooter_reservations : reserves
  users ||--o{ scooter_rentals : rents
  addresses ||--o{ restaurants : locates
  addresses ||--o{ orders : pickup
  addresses ||--o{ orders : dropoff
  restaurants o|--o{ orders : prepares
  restaurants ||--o{ menu_items : offers
  menu_categories ||--o{ menu_items : classifies
  service_types ||--o{ tariffs : prices
  service_types ||--o{ orders : identifies
  tariffs ||--o{ orders : quoted_with
  tariffs ||--o{ scooter_rentals : rented_with
  tariffs o|--o{ scooter_reservations : booked_with
  orders ||--o{ order_items : contains
  menu_items ||--o{ order_items : source
  orders ||--o{ order_status_history : changes
  order_statuses ||--o{ orders : current
  order_statuses ||--o{ order_status_history : transition
  performers o|--o{ orders : handles
  scooters ||--o{ scooter_reservations : reserved
  scooter_reservations ||--o| scooter_rentals : starts
  scooters ||--o{ scooter_rentals : rented
  scooter_rentals ||--o{ rental_status_history : changes
  orders ||--o| payments : pays
  scooter_rentals ||--o| payments : pays
  orders ||--o| reviews : receives
  orders {
    uuid id PK
    uuid tariff_id FK
    numeric surge_multiplier
    numeric discount_amount
    numeric total_amount
  }
  parking_zones {
    uuid id PK
    geometry boundary
    string kind
    boolean active
  }
  login_failures {
    text email_hash
    timestamptz attempted_at
  }
  schema_versions {
    int version PK
  }
```

Основные сущности используют UUID; коды справочников `roles`, `service_types`, `order_statuses` — текстовые ключи. `user_roles` имеет составной ключ `(user_id, role_code)`. Потенциальные ключи: `users.email`, `scooters.code`, `scooters.qr_code`, `menu_items(restaurant_id,name)`, `sessions.token_hash`. Внешние ключи связывают заказ с клиентом, типом услуги, тарифом, адресами и назначенным исполнителем. `order_items` и `user_roles` хранят многозначные связи отдельными строками. Метаданные аудита не используются как источник основных бизнес-связей.

| Поле | Назначение |
| --- | --- |
| `orders.customer_id`, `service_type_code`, `tariff_id` | Владелец, услуга и применённая версия тарифа |
| `orders.pickup_snapshot`, `dropoff_snapshot` | Адресные строки на момент оформления |
| `orders.pickup_lat_snapshot`, `pickup_lng_snapshot`, `dropoff_lat_snapshot`, `dropoff_lng_snapshot` | Географические точки на момент оформления |
| `orders.route_geometry` | Линия маршрута OSRM на момент оформления; сохраняется для карты после перезагрузки |
| `orders.restaurant_name_snapshot` | Название заведения при покупке |
| `orders.delivery_amount`, `discount_amount`, `total_amount` | Компоненты серверного расчёта в тенге |
| `order_items.item_name_snapshot`, `unit_price`, `quantity` | Купленное блюдо, цена и количество, независимо от действующего меню |
| `scooter_reservations.expires_at` | Серверный срок окончания брони |
| `scooter_reservations.tariff_id`, `demo_qr_token` | Версия тарифа и токен учебного QR. Для старой брони без версии сервер выбирает тариф при старте |
| `orders.surge_multiplier` | Множитель цены такси на момент создания. Для прежних заказов и доставки равен 1 |
| `login_failures` | Хеш почты и время ошибки пароля для скользящего пятиминутного окна |
| `scooter_rentals.started_at`, `ended_at` | UTC-моменты для итогового расчёта |
| `parking_zones.boundary` | Полигон PostGIS, WGS84 / SRID 4326 |

Основные функциональные зависимости: `user_id → email, full_name, password_hash`; `menu_item_id → restaurant_id, category_id, current_price`; `order_id → customer_id, service_type_code, tariff_id, status_code, total_amount`; `order_item_id → order_id, menu_item_id, purchased_quantity, purchased_unit_price`. Непосредственные факты о текущем каталоге живут в таблицах каталога, а состояния — в заказе и хронологии переходов. Повторяющихся групп и строковых списков ключей нет. Снимки сделки намеренно дублируют текущие адреса и позиции меню: это отдельные факты *на дату покупки*, поэтому изменение справочника не может пересчитать старый заказ. Использованный тариф защищён от UPDATE и DELETE; новые правила оформляются новой версией. Защитный триггер запрещает изменение исторических денежных и адресных полей заказа.

Статусы такси: `pending → assigned → accepted → arriving → in_progress → completed`. Статусы еды: `pending → preparing → assigned → accepted → picked_up → completed`. Отмена возможна только на ранних стадиях и проверяется сервером. Каждое изменение статуса и назначение проходят в транзакции с `FOR UPDATE`; история содержит исходный и новый статусы и инициатора. Частичные уникальные индексы исключают одновременные активные брони/аренды для самоката и клиента. Истечение брони проверяется сервером при операциях даже после его перезапуска. Завершение аренды требует активной парковки внутри активной зоны обслуживания; пересечение с активной запретной зоной отклоняется. Граница включается по `ST_Covers`. Координаты — градусы широты/долготы, расстояние автомобильного маршрута — метры, длительность — секунды, деньги — `NUMERIC(12,2)` и серверный `Decimal`.
