"""DAG template (R4): one function builds the full pipeline for one source.

    start_run -> extract_and_validate -> transform -> quality_gate
              -> load -> post_load_checks -> finish_run

extract_and_validate = extract + save_raw + parse + validate in one task, because
the connectors (R1) do those steps together in `connector.run(store=True)`.
Every run is written to ops.* through src/common/ops_log.py.
A task that fails for good (after its retries) marks the run as 'failed'.
"""
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.operators.python import PythonOperator

from src.common import ops_log

SQL_LOAD_DIR = Path("/opt/airflow/sql/load")   # ./sql is mounted at /opt/airflow/sql


def _run_id(ti):
    return ti.xcom_pull(task_ids="start_run")


def _on_failure(context):
    """Called when a task fails for good (retries used up): mark the run failed."""
    run_id = _run_id(context["ti"])
    if run_id:
        error = str(context.get("exception"))[:1000]
        ops_log.finish_run(run_id, "failed", error_message=error)


def _count(sql, params=()):
    with ops_log.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def make_source_dag(dag_id, source, connector_cls, staging_fn, staging_table,
                    fact_table, load_sql, schedule="0 6 * * *", retries=3):
    """Build the DAG for one source (daily at 06:00 Cairo by default)."""

    def start_run():
        return ops_log.start_run(dag_id, source)

    def extract_and_validate(ti):
        valid, rejected = connector_cls().run(store=True)   # fetch + raw + parse + validate
        ops_log.log_rejected_rows(source, "validate", rejected, _run_id(ti))
        return {"valid": len(valid), "rejected": len(rejected)}

    def transform():
        staging_fn()                                          # rebuild staging from raw

    def quality_gate(ti):
        """Critical checks BEFORE load. A failed critical check stops the DAG."""
        run_id = _run_id(ti)
        rows = _count(f"SELECT count(*) FROM {staging_table} WHERE source = %s", (source,))
        passed = rows > 0
        ops_log.log_quality(run_id, source, "row_count", "critical", "pre_load",
                            passed, rows, f"{rows} rows in {staging_table}")
        if not passed:
            raise AirflowFailException(f"quality_gate: no rows in {staging_table} for {source}")
        # TODO (tasks 5.4-5.6): nulls, duplicates, price_range

    def load():
        path = SQL_LOAD_DIR / load_sql
        if not path.exists():
            raise FileNotFoundError(f"{path} not found (is ./sql mounted and R3's load SQL merged?)")
        with ops_log.get_conn() as conn:
            conn.autocommit = True        # the SQL file has its own BEGIN ... COMMIT
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))

    def post_load_checks(ti):
        """Warning checks AFTER load: they are only logged, never fail the DAG."""
        run_id = _run_id(ti)
        rows = _count(f"SELECT count(*) FROM {fact_table} "
                      "WHERE loaded_at >= now() - interval '1 day'")
        ops_log.log_quality(run_id, source, "row_count", "warning", "post_load",
                            rows > 0, rows, f"{rows} rows written to {fact_table} in the last day")
        # TODO (tasks 5.5, 5.7): price_jump, freshness

    def finish_run(ti):
        stats = ti.xcom_pull(task_ids="extract_and_validate") or {}
        ops_log.finish_run(_run_id(ti), "success", records_count=stats.get("valid"))

    with DAG(
        dag_id=dag_id,
        start_date=pendulum.datetime(2026, 10, 1, tz="Africa/Cairo"),
        schedule=schedule,
        catchup=False,
        default_args={
            "retries": retries,
            "retry_delay": timedelta(minutes=5),
            "on_failure_callback": _on_failure,
        },
        tags=[source, "r4"],
    ) as dag:
        tasks = [
            PythonOperator(task_id=fn.__name__, python_callable=fn)
            for fn in (start_run, extract_and_validate, transform, quality_gate,
                       load, post_load_checks, finish_run)
        ]
        for upstream, downstream in zip(tasks, tasks[1:]):
            upstream >> downstream
    return dag