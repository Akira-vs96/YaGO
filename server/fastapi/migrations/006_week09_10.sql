-- Preserve the route shown to a customer after the order has been created.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS route_geometry jsonb;
ALTER TABLE orders ADD CONSTRAINT orders_route_linestring
    CHECK (route_geometry IS NULL OR route_geometry->>'type' = 'LineString');

CREATE OR REPLACE FUNCTION protect_order_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.pickup_snapshot, OLD.dropoff_snapshot,
     OLD.pickup_lat_snapshot, OLD.pickup_lng_snapshot,
     OLD.dropoff_lat_snapshot, OLD.dropoff_lng_snapshot,
     OLD.restaurant_name_snapshot, OLD.total_amount, OLD.discount_amount,
     OLD.delivery_amount, OLD.tariff_id, OLD.route_geometry)
    IS DISTINCT FROM
    (NEW.pickup_snapshot, NEW.dropoff_snapshot,
     NEW.pickup_lat_snapshot, NEW.pickup_lng_snapshot,
     NEW.dropoff_lat_snapshot, NEW.dropoff_lng_snapshot,
     NEW.restaurant_name_snapshot, NEW.total_amount, NEW.discount_amount,
     NEW.delivery_amount, NEW.tariff_id, NEW.route_geometry) THEN
  RAISE EXCEPTION 'Historical order facts are immutable' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END $$;

INSERT INTO schema_versions(version) VALUES (7) ON CONFLICT DO NOTHING;
