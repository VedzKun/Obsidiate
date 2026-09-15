-- Safe: DROP TABLE WITH a down migration defined inline.
-- The -- Down marker signals this migration is reversible.

DROP TABLE temp_import_staging;

-- Down
CREATE TABLE temp_import_staging (
    id SERIAL PRIMARY KEY,
    raw_data TEXT,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);
