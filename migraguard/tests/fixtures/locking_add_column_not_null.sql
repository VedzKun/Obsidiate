-- MG001 Trigger: ADD COLUMN NOT NULL with a non-null DEFAULT (high)
-- Full table rewrite on PG < 11. Lock risk on any version without lock_timeout.
ALTER TABLE users
    ADD COLUMN account_status VARCHAR(20) NOT NULL DEFAULT 'active';
