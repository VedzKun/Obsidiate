-- MG001 Trigger: ADD CONSTRAINT FOREIGN KEY without NOT VALID (high)
-- Scans the entire table to validate existing rows under ACCESS EXCLUSIVE lock.
ALTER TABLE order_items
    ADD CONSTRAINT fk_order_items_product
    FOREIGN KEY (product_id) REFERENCES products(id);
