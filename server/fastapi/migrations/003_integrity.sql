-- Additive integrity rules and immutable historical address snapshots.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_snapshot varchar(500);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS dropoff_snapshot varchar(500);
UPDATE orders o SET pickup_snapshot = p.address_text, dropoff_snapshot = d.address_text
FROM addresses p, addresses d
WHERE o.pickup_address_id = p.id AND o.dropoff_address_id = d.id
  AND (o.pickup_snapshot IS NULL OR o.dropoff_snapshot IS NULL);

CREATE OR REPLACE FUNCTION check_order_service() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM service_types WHERE code=NEW.service_type_code AND active) THEN
  RAISE EXCEPTION 'Inactive service type: %', NEW.service_type_code USING ERRCODE='check_violation';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM tariffs WHERE id=NEW.tariff_id AND service_type_code=NEW.service_type_code) THEN
  RAISE EXCEPTION 'Tariff belongs to another service' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_order_service ON orders;
CREATE TRIGGER trg_order_service BEFORE INSERT ON orders
FOR EACH ROW EXECUTE FUNCTION check_order_service();

CREATE OR REPLACE FUNCTION protect_order_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.pickup_snapshot, OLD.dropoff_snapshot, OLD.total_amount, OLD.tariff_id)
    IS DISTINCT FROM
    (NEW.pickup_snapshot, NEW.dropoff_snapshot, NEW.total_amount, NEW.tariff_id) THEN
  RAISE EXCEPTION 'Historical order facts are immutable' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_protect_order_snapshots ON orders;
CREATE TRIGGER trg_protect_order_snapshots BEFORE UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION protect_order_snapshots();

ALTER TABLE order_status_history ADD COLUMN IF NOT EXISTS from_status varchar(40) REFERENCES order_statuses(code);
CREATE INDEX IF NOT EXISTS ix_reservations_expiry ON scooter_reservations(expires_at) WHERE status='active';
CREATE INDEX IF NOT EXISTS ix_sessions_user_active ON sessions(user_id,expires_at) WHERE revoked_at IS NULL;
INSERT INTO schema_versions(version) VALUES (4) ON CONFLICT DO NOTHING;
