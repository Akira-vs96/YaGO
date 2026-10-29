-- Optional TOTP second factor and explicit demo student eligibility.
ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_secret text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_pending_secret text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS student_verified boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS login_challenges (
 token_hash char(64) PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL,
 failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts BETWEEN 0 AND 5),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_login_challenges_expires ON login_challenges(expires_at);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount numeric(12,2) NOT NULL DEFAULT 0
 CHECK (discount_amount >= 0);
CREATE OR REPLACE FUNCTION protect_order_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (OLD.pickup_snapshot, OLD.dropoff_snapshot, OLD.total_amount, OLD.discount_amount, OLD.tariff_id)
    IS DISTINCT FROM
    (NEW.pickup_snapshot, NEW.dropoff_snapshot, NEW.total_amount, NEW.discount_amount, NEW.tariff_id) THEN
  RAISE EXCEPTION 'Historical order facts are immutable' USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END $$;
INSERT INTO schema_versions(version) VALUES (5) ON CONFLICT DO NOTHING;
