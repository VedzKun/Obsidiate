-- MG003 Trigger: DROP TABLE with no down migration.
-- This is the acceptance criteria fixture: risky_migration.sql
-- Also triggers MG001 (ADD COLUMN NOT NULL DEFAULT) for the compound test.

-- Dangerous: full table rewrite on PG < 11
ALTER TABLE users
    ADD COLUMN account_status VARCHAR(20) NOT NULL DEFAULT 'active';

-- Irreversible: data loss
DROP TABLE legacy_sessions;

-- Type change: full rewrite
ALTER TABLE orders
    ALTER COLUMN total TYPE NUMERIC(14, 4);
