-- MG001 Trigger: ALTER COLUMN type change (critical)
-- This rewrites the entire table under ACCESS EXCLUSIVE lock.
ALTER TABLE orders
    ALTER COLUMN total_amount TYPE NUMERIC(12, 4);
