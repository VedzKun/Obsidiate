-- Safe: ADD CONSTRAINT FK with NOT VALID — safe two-step pattern.
-- Step 1: Add constraint without scanning existing rows (brief lock only).
ALTER TABLE order_items
    ADD CONSTRAINT fk_order_items_product
    FOREIGN KEY (product_id) REFERENCES products(id) NOT VALID;

-- Step 2: Validate separately (ShareUpdateExclusiveLock, does not block reads).
ALTER TABLE order_items VALIDATE CONSTRAINT fk_order_items_product;
