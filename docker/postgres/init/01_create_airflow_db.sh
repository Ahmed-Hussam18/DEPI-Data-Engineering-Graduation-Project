#!/bin/bash
# Runs once, only when the pgdata volume is empty (first start).
# POSTGRES_DB (eco) is created by the image itself; here we add the airflow database.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE DATABASE "${AIRFLOW_DB:-airflow}";
EOSQL
