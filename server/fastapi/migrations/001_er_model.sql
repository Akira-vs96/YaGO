CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['restaurants', 'menu_items', 'performers', 'orders', 'order_items']
    LOOP
        IF to_regclass(table_name) IS NOT NULL
           AND (
               (table_name = 'restaurants' AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'restaurants' AND column_name = 'owner_user_id'
               ))
               OR (table_name = 'menu_items' AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'menu_items' AND column_name = 'category_id'
               ))
               OR (table_name = 'performers' AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'performers' AND column_name = 'user_id'
               ))
               OR (table_name = 'orders' AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'orders' AND column_name = 'customer_id'
               ))
               OR (table_name = 'order_items' AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'order_items' AND column_name = 'item_name_snapshot'
               ))
           )
        THEN
            EXECUTE format('
                DO $nested$
                BEGIN
                    IF EXISTS (SELECT 1 FROM %I LIMIT 1) THEN
                        RAISE EXCEPTION ''Cannot migrate non-empty legacy table %I automatically'';
                    END IF;
                END
                $nested$', table_name, table_name);
            EXECUTE format('ALTER TABLE %I RENAME TO %I', table_name, 'legacy_' || table_name);
        END IF;
    END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(255) NOT NULL UNIQUE,
    phone varchar(32) UNIQUE,
    password_hash text NOT NULL DEFAULT '',
    full_name varchar(120) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS roles (
    code varchar(32) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_code varchar(32) NOT NULL REFERENCES roles(code) ON DELETE RESTRICT,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_code)
);

CREATE TABLE IF NOT EXISTS addresses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label varchar(120) NOT NULL,
    address_text varchar(500) NOT NULL,
    lat numeric(9, 6) NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng numeric(9, 6) NOT NULL CHECK (lng BETWEEN -180 AND 180),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS restaurants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    address_id uuid REFERENCES addresses(id) ON DELETE RESTRICT,
    name varchar(120) NOT NULL,
    cuisine varchar(120) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    lat double precision NOT NULL DEFAULT 51.1694,
    lng double precision NOT NULL DEFAULT 71.4491,
    address varchar(500),
    eta integer NOT NULL DEFAULT 25,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS menu_categories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS menu_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    restaurant_id uuid NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    category_id uuid REFERENCES menu_categories(id) ON DELETE RESTRICT,
    name varchar(120) NOT NULL,
    description text,
    price numeric(12, 2) NOT NULL CHECK (price >= 0),
    is_available boolean NOT NULL DEFAULT true,
    category varchar(80) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS performers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    address_id uuid REFERENCES addresses(id) ON DELETE SET NULL,
    type varchar(32) NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'available',
    created_at timestamptz NOT NULL DEFAULT now(),
    name varchar(120) NOT NULL DEFAULT '',
    role varchar(20) NOT NULL DEFAULT 'courier',
    lat double precision NOT NULL DEFAULT 51.1694,
    lng double precision NOT NULL DEFAULT 71.4491
);

CREATE TABLE IF NOT EXISTS service_types (
    code varchar(32) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS order_statuses (
    code varchar(32) PRIMARY KEY,
    name varchar(120) NOT NULL UNIQUE,
    is_final boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS tariffs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_type_code varchar(32) NOT NULL REFERENCES service_types(code) ON DELETE RESTRICT,
    name varchar(120) NOT NULL,
    base_fare numeric(12, 2) NOT NULL DEFAULT 0 CHECK (base_fare >= 0),
    price_per_km numeric(12, 2) NOT NULL DEFAULT 0 CHECK (price_per_km >= 0),
    price_per_minute numeric(12, 2) NOT NULL DEFAULT 0 CHECK (price_per_minute >= 0),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz
);

CREATE TABLE IF NOT EXISTS orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    service_type_code varchar(32) REFERENCES service_types(code) ON DELETE RESTRICT,
    status_code varchar(32) REFERENCES order_statuses(code) ON DELETE RESTRICT,
    tariff_id uuid REFERENCES tariffs(id) ON DELETE RESTRICT,
    pickup_address_id uuid REFERENCES addresses(id) ON DELETE RESTRICT,
    dropoff_address_id uuid REFERENCES addresses(id) ON DELETE RESTRICT,
    restaurant_id uuid REFERENCES restaurants(id) ON DELETE SET NULL,
    performer_id uuid REFERENCES performers(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    completed_at timestamptz,
    customer varchar(120) NOT NULL DEFAULT '',
    type varchar(20) NOT NULL DEFAULT 'taxi',
    status varchar(20) NOT NULL DEFAULT 'pending',
    total integer NOT NULL DEFAULT 0,
    start jsonb NOT NULL DEFAULT '{}'::jsonb,
    "end" jsonb NOT NULL DEFAULT '{}'::jsonb,
    courier_id uuid
);

CREATE TABLE IF NOT EXISTS order_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    menu_item_id uuid NOT NULL REFERENCES menu_items(id) ON DELETE RESTRICT,
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(12, 2) NOT NULL CHECK (unit_price >= 0),
    item_name_snapshot varchar(120),
    name varchar(120) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS order_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status_code varchar(32) NOT NULL REFERENCES order_statuses(code) ON DELETE RESTRICT,
    changed_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    comment text
);

INSERT INTO roles (code, name) VALUES
    ('client', 'Клиент'),
    ('courier', 'Курьер'),
    ('driver', 'Водитель'),
    ('restaurant', 'Ресторан'),
    ('admin', 'Администратор')
ON CONFLICT (code) DO NOTHING;

INSERT INTO service_types (code, name) VALUES
    ('food', 'Доставка еды'),
    ('taxi', 'Такси'),
    ('scooter', 'Аренда самоката'),
    ('bike', 'Аренда велосипеда')
ON CONFLICT (code) DO NOTHING;

INSERT INTO order_statuses (code, name, is_final) VALUES
    ('pending', 'Создан', false),
    ('assigned', 'Назначен', false),
    ('in_progress', 'Выполняется', false),
    ('completed', 'Завершён', true),
    ('cancelled', 'Отменён', true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO menu_categories (name) VALUES ('Основное')
ON CONFLICT (name) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_addresses_user_id ON addresses(user_id);
CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS ix_orders_status_code ON orders(status_code);
CREATE INDEX IF NOT EXISTS ix_order_events_order_id_changed_at ON order_events(order_id, changed_at);
