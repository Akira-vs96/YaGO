ALTER TABLE orders ADD COLUMN surge_multiplier numeric(3,2) NOT NULL DEFAULT 1
    CHECK (surge_multiplier >= 1);

CREATE FUNCTION protect_order_multiplier() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.surge_multiplier IS DISTINCT FROM NEW.surge_multiplier THEN
        RAISE EXCEPTION 'Historical demand multiplier is immutable' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_order_multiplier BEFORE UPDATE OF surge_multiplier ON orders
    FOR EACH ROW EXECUTE FUNCTION protect_order_multiplier();

CREATE TABLE login_failures (
    email_hash text NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ix_login_failures_email ON login_failures(email_hash);
CREATE INDEX ix_login_failures_time ON login_failures(attempted_at);
INSERT INTO schema_versions(version) VALUES (9);
