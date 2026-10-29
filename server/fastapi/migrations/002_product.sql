-- Additive upgrade of the historical v2 schema. Existing orders and users stay intact.
CREATE EXTENSION IF NOT EXISTS postgis;

ALTER TABLE service_types ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
UPDATE service_types SET active = false WHERE code IN ('bike', 'bicycle');
INSERT INTO service_types (code, name, active) VALUES ('scooter', 'Электросамокаты', true)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, active = true;

INSERT INTO roles (code, name) VALUES ('operator', 'Оператор'), ('performer', 'Исполнитель')
ON CONFLICT (code) DO NOTHING;
INSERT INTO order_statuses (code, name) VALUES
 ('accepted', 'Принят'), ('arriving', 'Едет к клиенту'),
 ('preparing', 'Готовится'), ('picked_up', 'Забран курьером')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS csrf_hash text;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE orders ADD COLUMN IF NOT EXISTS total_amount numeric(12,2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS distance_meters integer;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS duration_seconds integer;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key varchar(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS request_hash char(64);
ALTER TABLE orders ADD CONSTRAINT orders_total_nonnegative CHECK (total_amount IS NULL OR total_amount >= 0);
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_customer_idempotency ON orders(customer_id, idempotency_key)
 WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_orders_customer_created ON orders(customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_orders_status_created ON orders(status_code, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_performer_active ON orders(performer_id)
 WHERE performer_id IS NOT NULL AND status_code NOT IN ('completed', 'cancelled');

CREATE TABLE IF NOT EXISTS scooters (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 code varchar(40) NOT NULL UNIQUE,
 qr_code varchar(80) NOT NULL UNIQUE,
 lat numeric(9,6) NOT NULL CHECK (lat BETWEEN -90 AND 90),
 lng numeric(9,6) NOT NULL CHECK (lng BETWEEN -180 AND 180),
 battery_percent integer NOT NULL CHECK (battery_percent BETWEEN 0 AND 100),
 status varchar(20) NOT NULL DEFAULT 'available'
  CHECK (status IN ('available','reserved','in_use','maintenance','blocked')),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_scooters_status ON scooters(status);

CREATE TABLE IF NOT EXISTS parking_zones (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name varchar(120) NOT NULL UNIQUE,
 boundary geometry(Polygon,4326) NOT NULL,
 active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_parking_zones_boundary ON parking_zones USING gist(boundary);

CREATE TABLE IF NOT EXISTS scooter_reservations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 scooter_id uuid NOT NULL REFERENCES scooters(id),
 customer_id uuid NOT NULL REFERENCES users(id),
 status varchar(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','started','expired','cancelled')),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 idempotency_key varchar(100),
 request_hash char(64),
 CHECK (expires_at > created_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reservation_scooter_active ON scooter_reservations(scooter_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_reservation_customer_active ON scooter_reservations(customer_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_reservation_idempotency ON scooter_reservations(customer_id,idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS scooter_rentals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 reservation_id uuid NOT NULL UNIQUE REFERENCES scooter_reservations(id),
 scooter_id uuid NOT NULL REFERENCES scooters(id),
 customer_id uuid NOT NULL REFERENCES users(id),
 tariff_id uuid NOT NULL REFERENCES tariffs(id),
 status varchar(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed')),
 started_at timestamptz NOT NULL DEFAULT now(),
 ended_at timestamptz,
 end_lat numeric(9,6),
 end_lng numeric(9,6),
 total_amount numeric(12,2) CHECK (total_amount IS NULL OR total_amount >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rental_scooter_active ON scooter_rentals(scooter_id) WHERE status='active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_rental_customer_active ON scooter_rentals(customer_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS ix_rentals_customer_started ON scooter_rentals(customer_id,started_at DESC);

CREATE TABLE IF NOT EXISTS rental_status_history (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 rental_id uuid NOT NULL REFERENCES scooter_rentals(id),
 from_status varchar(20), to_status varchar(20) NOT NULL,
 actor_id uuid REFERENCES users(id), changed_at timestamptz NOT NULL DEFAULT now(), reason text
);
CREATE TABLE IF NOT EXISTS reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 order_id uuid NOT NULL UNIQUE REFERENCES orders(id),
 customer_id uuid NOT NULL REFERENCES users(id),
 rating integer NOT NULL CHECK (rating BETWEEN 1 AND 5),
 comment varchar(1000), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 order_id uuid UNIQUE REFERENCES orders(id),
 rental_id uuid UNIQUE REFERENCES scooter_rentals(id),
 amount numeric(12,2) NOT NULL CHECK (amount >= 0),
 status varchar(20) NOT NULL DEFAULT 'paid' CHECK (status IN ('paid','refunded')),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((order_id IS NULL) <> (rental_id IS NULL))
);
CREATE TABLE IF NOT EXISTS audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
 action varchar(80) NOT NULL,
 subject_type varchar(40), subject_id varchar(80),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_events(created_at DESC);

-- An already used tariff is a historical price rule, so it cannot be edited or deleted.
CREATE OR REPLACE FUNCTION protect_used_tariff() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM orders WHERE tariff_id=OLD.id)
 OR EXISTS (SELECT 1 FROM scooter_rentals WHERE tariff_id=OLD.id) THEN
  RAISE EXCEPTION 'Used tariff versions are immutable';
 END IF;
 RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS trg_protect_used_tariff ON tariffs;
CREATE TRIGGER trg_protect_used_tariff BEFORE UPDATE OR DELETE ON tariffs
FOR EACH ROW EXECUTE FUNCTION protect_used_tariff();

INSERT INTO tariffs(service_type_code,name,base_fare,price_per_km,price_per_minute,valid_from)
SELECT 'scooter','Стандарт · самокат',100,0,35,now()
WHERE NOT EXISTS (SELECT 1 FROM tariffs WHERE service_type_code='scooter' AND valid_to IS NULL);

INSERT INTO schema_versions(version) VALUES (3) ON CONFLICT DO NOTHING;
