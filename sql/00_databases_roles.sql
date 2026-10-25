-- 00_databases_roles.sql
-- Owner: R3 (Warehouse & SQL Lead)
--
-- Executed by docker/postgres/init/02_run_sql.sh as the admin user
-- (POSTGRES_USER) against db `eco`, only on first start (empty volume).
--
-- Already handled elsewhere (do NOT recreate here):
--   * db `eco`     -> created by the postgres image (POSTGRES_DB)
--   * db `airflow` -> created by docker/postgres/init/01_create_airflow_db.sh
--
-- Passwords are NOT in this file: they come from .env through psql
-- variables (etl_pw / reader_pw), set by 02_run_sql.sh.

CREATE ROLE etl_user LOGIN PASSWORD :'etl_pw';
CREATE ROLE reader   LOGIN PASSWORD :'reader_pw';

-- Nobody gets implicit access to eco through PUBLIC.
REVOKE ALL ON DATABASE eco FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE eco TO etl_user;
GRANT CONNECT ON DATABASE eco TO reader;