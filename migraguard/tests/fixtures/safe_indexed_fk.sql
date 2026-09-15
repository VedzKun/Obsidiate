-- Safe: FK column with CREATE INDEX CONCURRENTLY in the same migration.
-- The index is created before the FK constraint — safe pattern.

-- Step 1: Add the column (nullable).
ALTER TABLE order_items
    ADD COLUMN user_id INT;

-- Step 2: Index first (no table lock, runs concurrently).
CREATE INDEX CONCURRENTLY idx_order_items_user_id ON order_items (user_id);

-- Step 3: Add the constraint with NOT VALID (brief lock only).
ALTER TABLE order_items
    ADD CONSTRAINT fk_order_items_user
        FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;

-- Step 4: Validate separately.
ALTER TABLE order_items VALIDATE CONSTRAINT fk_order_items_user;
