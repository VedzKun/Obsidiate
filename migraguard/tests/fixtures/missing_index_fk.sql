-- MG002 Trigger: ADD CONSTRAINT FK with no corresponding index.
-- Joins and cascade deletes on order_items.user_id will be sequential scans.
ALTER TABLE order_items
    ADD COLUMN user_id INT NOT NULL,
    ADD CONSTRAINT fk_order_items_user
        FOREIGN KEY (user_id) REFERENCES users(id);
