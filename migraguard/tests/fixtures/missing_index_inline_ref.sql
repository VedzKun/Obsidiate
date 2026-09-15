-- MG002 Trigger: inline REFERENCES on ADD COLUMN with no index.
-- The inline FK syntax is syntactic sugar for ADD CONSTRAINT FOREIGN KEY.
ALTER TABLE comments
    ADD COLUMN post_id INT REFERENCES posts(id);
