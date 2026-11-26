"""Write monitoring rows to ops.* (owner: R4).

All writes to ops.pipeline_runs / ops.records_rejected / ops.quality_results
go through this module (code rule: nobody else writes to ops).

Connection lookup is the same as src/common/raw_store.py:
  1. ECO_DB_URL   2. AIRFLOW_CONN_ECO_DB (set inside the Airflow containers)
  3. POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB / ETL_USER / ETL_USER_PASSWORD
"""
import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg2

CAIRO = ZoneInfo("Africa/Cairo")


def cairo_today() -> date:
    return datetime.now(CAIRO).date()


def _connect():
    """Same lookup order as src/common/raw_store.py."""
    url = os.getenv("ECO_DB_URL") or os.getenv("AIRFLOW_CONN_ECO_DB")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "eco"),
        user=os.getenv("ETL_USER", "etl_user"),
        password=os.getenv("ETL_USER_PASSWORD"),
    )


@contextmanager
def get_conn():
    """Commit on success, rollback on error, always close."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def start_run(dag_id: str, source: str, run_date: date | None = None) -> int:
    """Insert a 'running' row and return its run_id."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.pipeline_runs (dag_id, source, run_date) "
            "VALUES (%s, %s, %s) RETURNING run_id",
            (dag_id, source, run_date or cairo_today()),
        )
        return cur.fetchone()[0]


def finish_run(run_id: int, status: str, records_count: int | None = None,
               error_message: str | None = None) -> None:
    """status: 'success' or 'failed'."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.pipeline_runs "
            "SET status = %s, finished_at = now(), records_count = %s, error_message = %s "
            "WHERE run_id = %s",
            (status, records_count, error_message, run_id),
        )


def log_rejected(run_id: int, source: str, stage: str, reason: str,
                 record: dict | None = None) -> None:
    """stage: 'validate' (structural) or 'transform' (logical)."""
    payload = json.dumps(record, default=str, ensure_ascii=False) if record is not None else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.records_rejected (run_id, source, stage, reason, record) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, source, stage, reason, payload),
        )


def log_rejected_rows(run_id: int, source: str, stage: str, rejected_rows: list) -> int:
    """Log the [{"reason":..., "record":...}] list returned by connector.validate()."""
    for r in rejected_rows:
        log_rejected(run_id, source, stage, r["reason"], r.get("record"))
    return len(rejected_rows)


def log_quality(run_id: int, source: str, check_name: str, severity: str,
                phase: str, passed: bool, metric_value: float | None = None,
                details: str | None = None) -> None:
    """severity: 'critical' | 'warning'.  phase: 'pre_load' | 'post_load'."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.quality_results "
            "(run_id, source, check_name, severity, phase, passed, metric_value, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, source, check_name, severity, phase, passed, metric_value, details),
        )