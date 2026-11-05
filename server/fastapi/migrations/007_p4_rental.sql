ALTER TABLE scooter_reservations
    ADD COLUMN tariff_id uuid REFERENCES tariffs(id),
    ADD COLUMN demo_qr_token uuid NOT NULL DEFAULT gen_random_uuid();

CREATE INDEX ix_reservation_tariff ON scooter_reservations(tariff_id);

CREATE OR REPLACE FUNCTION protect_used_tariff() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM orders WHERE tariff_id=OLD.id)
       OR EXISTS (SELECT 1 FROM scooter_reservations WHERE tariff_id=OLD.id)
       OR EXISTS (SELECT 1 FROM scooter_rentals WHERE tariff_id=OLD.id) THEN
        RAISE EXCEPTION 'Used tariff versions are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

ALTER TABLE parking_zones
    ADD COLUMN kind varchar(12) NOT NULL DEFAULT 'parking'
    CHECK (kind IN ('service', 'parking', 'no_parking'));

-- Existing parking areas keep working after the upgrade.
INSERT INTO parking_zones(name, boundary, kind)
SELECT 'Зона обслуживания · ' || id, boundary, 'service'
FROM parking_zones WHERE active AND kind='parking';

INSERT INTO schema_versions(version) VALUES (8);
