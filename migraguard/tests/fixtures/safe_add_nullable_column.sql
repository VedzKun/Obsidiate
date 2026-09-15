-- Safe: ADD COLUMN nullable, no default — metadata-only change, no lock risk.
ALTER TABLE users
    ADD COLUMN middle_name VARCHAR(100);
