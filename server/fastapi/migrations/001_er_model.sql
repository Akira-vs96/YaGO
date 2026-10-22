-- YaGo PostgreSQL schema based on docs/week-03/p3/yago-er-3nf.drawio.
-- Every non-key attribute belongs to one entity; M:N relations use bridge tables.
CREATE TABLE IF NOT EXISTS schema_versions (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = 2) THEN
        DROP TABLE IF EXISTS order_status_history, order_items, orders, tariffs,
            performers, menu_items, menu_categories, restaurants, sessions,
            addresses, user_roles, roles, service_types, order_statuses, users CASCADE;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(320) NOT NULL UNIQUE,
    phone varchar(32) UNIQUE,
    password_hash text,
    full_name varchar(120) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS roles (
    code varchar(40) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_code varchar(40) NOT NULL REFERENCES roles(code),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_code)
);

CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS addresses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES users(id) ON DELETE CASCADE,
    label varchar(80),
    address_text varchar(500) NOT NULL,
    lat numeric(9, 6) NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng numeric(9, 6) NOT NULL CHECK (lng BETWEEN -180 AND 180),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS restaurants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    address_id uuid NOT NULL REFERENCES addresses(id),
    name varchar(160) NOT NULL,
    cuisine varchar(120) NOT NULL,
    status varchar(40) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS menu_categories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS menu_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id uuid NOT NULL REFERENCES restaurants(id),
    category_id uuid NOT NULL REFERENCES menu_categories(id),
    name varchar(160) NOT NULL,
    description text,
    price numeric(12, 2) NOT NULL CHECK (price >= 0),
    is_available boolean NOT NULL DEFAULT true,
    UNIQUE (restaurant_id, name)
);

CREATE TABLE IF NOT EXISTS performers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    address_id uuid REFERENCES addresses(id) ON DELETE SET NULL,
    type varchar(40) NOT NULL CHECK (type IN ('courier', 'driver')),
    status varchar(40) NOT NULL DEFAULT 'available',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS service_types (
    code varchar(40) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tariffs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_type_code varchar(40) NOT NULL REFERENCES service_types(code),
    name varchar(120) NOT NULL,
    base_fare numeric(12, 2) NOT NULL DEFAULT 0 CHECK (base_fare >= 0),
    price_per_km numeric(12, 2) NOT NULL DEFAULT 0 CHECK (price_per_km >= 0),
    price_per_minute numeric(12, 2) NOT NULL DEFAULT 0 CHECK (price_per_minute >= 0),
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE IF NOT EXISTS order_statuses (
    code varchar(40) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES users(id),
    service_type_code varchar(40) NOT NULL REFERENCES service_types(code),
    status_code varchar(40) NOT NULL REFERENCES order_statuses(code),
    tariff_id uuid NOT NULL REFERENCES tariffs(id),
    pickup_address_id uuid NOT NULL REFERENCES addresses(id),
    dropoff_address_id uuid NOT NULL REFERENCES addresses(id),
    restaurant_id uuid REFERENCES restaurants(id),
    performer_id uuid REFERENCES performers(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    completed_at timestamptz,
    CHECK (completed_at IS NULL OR accepted_at IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS order_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id uuid NOT NULL REFERENCES menu_items(id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12, 2) NOT NULL CHECK (unit_price >= 0),
    item_name_snapshot varchar(160) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status_code varchar(40) NOT NULL REFERENCES order_statuses(code),
    changed_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    comment text
);

INSERT INTO roles(code, name) VALUES
    ('client', 'Клиент'), ('courier', 'Курьер'), ('driver', 'Водитель'),
    ('restaurant', 'Ресторан'), ('admin', 'Администратор')
ON CONFLICT DO NOTHING;

INSERT INTO service_types(code, name) VALUES
    ('food', 'Доставка еды'), ('taxi', 'Такси')
ON CONFLICT DO NOTHING;

INSERT INTO order_statuses(code, name) VALUES
    ('pending', 'Ожидает назначения'), ('assigned', 'Назначен'),
    ('in_progress', 'Выполняется'), ('completed', 'Завершён'),
    ('cancelled', 'Отменён')
ON CONFLICT DO NOTHING;

INSERT INTO menu_categories(name) VALUES ('Основное')
ON CONFLICT DO NOTHING;

INSERT INTO tariffs(
    service_type_code, name, base_fare, price_per_km, price_per_minute, valid_from
)
SELECT 'taxi', 'Базовый тариф такси', 500, 120, 0, now()
WHERE NOT EXISTS (
    SELECT 1 FROM tariffs WHERE service_type_code = 'taxi' AND valid_to IS NULL
);
INSERT INTO tariffs(
    service_type_code, name, base_fare, price_per_km, price_per_minute, valid_from
)
SELECT 'food', 'Базовый тариф доставки', 0, 0, 0, now()
WHERE NOT EXISTS (
    SELECT 1 FROM tariffs WHERE service_type_code = 'food' AND valid_to IS NULL
);

CREATE INDEX IF NOT EXISTS ix_addresses_user_id ON addresses(user_id);
CREATE INDEX IF NOT EXISTS ix_restaurants_address_id ON restaurants(address_id);
CREATE INDEX IF NOT EXISTS ix_menu_items_restaurant_id ON menu_items(restaurant_id);
CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_orders_performer_id ON orders(performer_id);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS ix_order_status_history_order_id_changed_at
    ON order_status_history(order_id, changed_at DESC);

INSERT INTO schema_versions(version) VALUES (2)
ON CONFLICT DO NOTHING;
