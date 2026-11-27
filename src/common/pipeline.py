"""DAG template (R4): one function builds the full pipeline for one source.

    start_run -> extract_and_validate -> transform -> quality_gate
              -> load -> post_load_checks -> finish_run

extract_and_validate = extract + save_raw + parse + validate in one task, because
the connectors (R1) do those steps together in `connector.run(store=True)`.
Every run is written to ops.* through src/common/ops_log.py.
A task that fails for good (after its retries) marks the run as 'failed'.
"""

import itertools
import logging
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.operators.python import PythonOperator

from src.common import ops_log
from src.quality.checks import run_post_load_checks, run_pre_load_checks

log = logging.getLogger(__name__)

SQL_LOAD_DIR = Path("/opt/airflow/sql/load")   # ./sql is mounted at /opt/airflow/sql


def _run_id(ti):
    return ti.xcom_pull(task_ids="start_run")


def _on_failure(context):
    """Called when a task fails for good (retries used up): mark the run failed."""
    run_id = _run_id(context["ti"])
    error = str(context.get("exception"))[:1000]
    log.error("DAG task failed permanently (run_id=%s): %s", run_id, error)
    if run_id:
        ops_log.finish_run(run_id, "failed", error_message=error)


def make_source_dag(dag_id, source, connector_cls, staging_fn, staging_table,
                    fact_table, load_sql, schedule="0 6 * * *", retries=3):
    """Build the DAG for one source (daily at 06:00 Cairo by default)."""

    def start_run():
        run_id = ops_log.start_run(dag_id, source)
        log.info("Started pipeline run_id=%s for dag=%s source=%s", run_id, dag_id, source)
        return run_id

    def extract_and_validate(ti):
        valid, rejected = connector_cls().run(store=True)   # fetch + raw + parse + validate
        ops_log.log_rejected_rows(source, "validate", rejected, _run_id(ti))
        log.info("Extracted source=%s valid=%d rejected=%d", source, len(valid), len(rejected))
        return {"valid": len(valid), "rejected": len(rejected)}

    def transform():
        written = staging_fn()                                # rebuild staging from raw
        log.info("Transformed source=%s rows=%s", source, written)

    def quality_gate(ti):
        """Critical checks BEFORE load. A failed critical check stops the DAG."""
        run_id = _run_id(ti)
        with ops_log.get_conn() as conn, conn.cursor() as cur:
            results = run_pre_load_checks(cur, run_id, source, staging_table)
        failed = [r for r in results if not r["passed"]]
        if failed:
            summary = "; ".join(f"{r['check_name']} ({r['details']})" for r in failed)
            log.error("quality_gate failed for %s: %s", source, summary)
            raise AirflowFailException(f"quality_gate failed for {source}: {summary}")
        log.info("quality_gate passed all %d critical checks for %s", len(results), source)

    def load():
        path = SQL_LOAD_DIR / load_sql
        if not path.exists():
            raise FileNotFoundError(f"{path} not found (is ./sql mounted and R3's load SQL merged?)")
        with ops_log.get_conn() as conn:
            conn.autocommit = True        # the SQL file has its own BEGIN ... COMMIT
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
        log.info("Loaded DWH for source=%s via %s", source, load_sql)

    def post_load_checks(ti):
        """Warning checks AFTER load: they are only logged, never fail the DAG."""
        run_id = _run_id(ti)
        with ops_log.get_conn() as conn, conn.cursor() as cur:
            results = run_post_load_checks(cur, run_id, source, fact_table)
        warnings = [r for r in results if not r["passed"]]
        if warnings:
            log.warning("post_load_checks warnings for %s: %s", source, warnings)
        else:
            log.info("post_load_checks passed all %d checks for %s", len(results), source)

    def finish_run(ti):
        stats = ti.xcom_pull(task_ids="extract_and_validate") or {}
        run_id = _run_id(ti)
        ops_log.finish_run(run_id, "success", records_count=stats.get("valid"))
        log.info("Finished pipeline run_id=%s status=success records=%s", run_id, stats.get("valid"))

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
        for upstream, downstream in itertools.pairwise(tasks):
            upstream >> downstream
    return dag