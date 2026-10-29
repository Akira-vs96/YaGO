-- Keep all customer-facing location facts independent of mutable address rows.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_lat_snapshot numeric(9,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_lng_snapshot numeric(9,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS dropoff_lat_snapshot numeric(9,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS dropoff_lng_snapshot numeric(9,6);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS restaurant_name_snapshot varchar(160);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_amount numeric(12,2)
 CHECK (delivery_amount IS NULL OR delivery_amount >= 0);
UPDATE orders o SET
 pickup_lat_snapshot=COALESCE(o.pickup_lat_snapshot,p.lat),
 pickup_lng_snapshot=COALESCE(o.pickup_lng_snapshot,p.lng),
 dropoff_lat_snapshot=COALESCE(o.dropoff_lat_snapshot,d.lat),
 dropoff_lng_snapshot=COALESCE(o.dropoff_lng_snapshot,d.lng),
 restaurant_name_snapshot=COALESCE(o.restaurant_name_snapshot,r.name)
FROM addresses p, addresses d, restaurants r
WHERE o.pickup_address_id=p.id AND o.dropoff_address_id=d.id AND o.restaurant_id=r.id;
UPDATE orders o SET
 pickup_lat_snapshot=COALESCE(o.pickup_lat_snapshot,p.lat),
 pickup_lng_snapshot=COALESCE(o.pickup_lng_snapshot,p.lng),
 dropoff_lat_snapshot=COALESCE(o.dropoff_lat_snapshot,d.lat),
 dropoff_lng_snapshot=COALESCE(o.dropoff_lng_snapshot,d.lng)
FROM addresses p, addresses d
WHERE o.pickup_address_id=p.id AND o.dropoff_address_id=d.id;

CREATE OR REPLACE FUNCTION protect_order_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.pickup_snapshot, OLD.dropoff_snapshot,
     OLD.pickup_lat_snapshot, OLD.pickup_lng_snapshot,
     OLD.dropoff_lat_snapshot, OLD.dropoff_lng_snapshot,
     OLD.restaurant_name_snapshot, OLD.total_amount, OLD.discount_amount,
     OLD.delivery_amount, OLD.tariff_id)
    IS DISTINCT FROM
    (NEW.pickup_snapshot, NEW.dropoff_snapshot,
     NEW.pickup_lat_snapshot, NEW.pickup_lng_snapshot,
     NEW.dropoff_lat_snapshot, NEW.dropoff_lng_snapshot,
     NEW.restaurant_name_snapshot, NEW.total_amount, NEW.discount_amount,
     NEW.delivery_amount, NEW.tariff_id) THEN
  RAISE EXCEPTION 'Historical order facts are immutable' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END $$;
INSERT INTO schema_versions(version) VALUES (6) ON CONFLICT DO NOTHING;
