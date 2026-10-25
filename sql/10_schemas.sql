-- 10_schemas.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- Creates the 5 schemas of db `eco` and sets who can touch what.
-- Runs as the admin user (already connected to eco by 02_run_sql.sh).

-- etl_user OWNS every schema. Objects created later by etl_user
-- (files 20..60 start with SET ROLE etl_user) are owned by etl_user too.
-- A view runs with its OWNER's privileges, so `reader` can SELECT a
-- serving view that reads dwh/ops without direct access to those schemas.
CREATE SCHEMA IF NOT EXISTS raw     AUTHORIZATION etl_user;
CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION etl_user;
CREATE SCHEMA IF NOT EXISTS dwh     AUTHORIZATION etl_user;
CREATE SCHEMA IF NOT EXISTS ops     AUTHORIZATION etl_user;
CREATE SCHEMA IF NOT EXISTS serving AUTHORIZATION etl_user;

-- Lock everything down first.
REVOKE ALL ON SCHEMA raw, staging, dwh, ops, serving FROM PUBLIC;

-- reader: serving only (views count as tables for default privileges).
GRANT USAGE ON SCHEMA serving TO reader;
ALTER DEFAULT PRIVILEGES FOR ROLE etl_user IN SCHEMA serving
    GRANT SELECT ON TABLES TO reader;

-- reader gets nothing on raw / staging / dwh / ops.