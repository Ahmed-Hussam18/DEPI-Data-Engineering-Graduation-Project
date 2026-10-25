#!/bin/bash
# Runs once, only when the pgdata volume is empty (first start).
# Executes every file in /sql (mounted from ./sql) in name order, against db eco.
# App-role passwords come from the environment (.env), never from the SQL files.
set -e

for f in /sql/*.sql; do
    [ -e "$f" ] || continue
    echo ">> running $f"
    psql -v ON_ERROR_STOP=1 \
         -v etl_pw="$ETL_USER_PASSWORD" \
         -v reader_pw="$READER_PASSWORD" \
         --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         -f "$f"
done