-- MG003 Trigger: DROP COLUMN with no down migration.
ALTER TABLE users
    DROP COLUMN legacy_token;
