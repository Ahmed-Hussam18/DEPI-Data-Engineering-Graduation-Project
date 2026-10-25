-- 50_ops.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- Monitoring tables. Written ONLY through src/common/ops_log.py (R4).
-- Exposed to the API / Grafana through views in `serving` (see 60_serving.sql),
-- never directly: reader has no access to schema ops.

SET ROLE etl_user;

-- One row per DAG run per source.
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id         BIGSERIAL PRIMARY KEY,
    dag_id         TEXT        NOT NULL,
    source         TEXT        NOT NULL,   -- same names as dwh.dim_source
    run_date       DATE        NOT NULL,   -- Africa/Cairo date of the run
    status         TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'success', 'failed')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    records_count  INTEGER,                -- records loaded in this run
    error_message  TEXT                    -- filled on final failure
);
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_source_time
    ON ops.pipeline_runs (source, started_at DESC);

-- Records that were rejected instead of being dropped silently.
-- stage = 'validate'  -> structural problem (missing field, wrong type), in the connector
-- stage = 'transform' -> logical problem (price <= 0, unknown unit), in cleaning
CREATE TABLE IF NOT EXISTS ops.records_rejected (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT REFERENCES ops.pipeline_runs (run_id) ON DELETE SET NULL,
    source       TEXT        NOT NULL,
    stage        TEXT        NOT NULL CHECK (stage IN ('validate', 'transform')),
    reason       TEXT        NOT NULL,
    record       JSONB,                    -- the rejected record as it was
    rejected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_records_rejected_run
    ON ops.records_rejected (run_id);
CREATE INDEX IF NOT EXISTS ix_records_rejected_source_time
    ON ops.records_rejected (source, rejected_at DESC);

-- Result of every data-quality check.
-- critical checks run BEFORE load (quality_gate) and fail the task;
-- warning checks run AFTER load (post_load_checks) and are only logged.
CREATE TABLE IF NOT EXISTS ops.quality_results (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT REFERENCES ops.pipeline_runs (run_id) ON DELETE SET NULL,
    source       TEXT        NOT NULL,
    check_name   TEXT        NOT NULL,     -- nulls, duplicates, price_range,
                                           -- price_jump, row_count, freshness
    severity     TEXT        NOT NULL CHECK (severity IN ('critical', 'warning')),
    phase        TEXT        NOT NULL CHECK (phase IN ('pre_load', 'post_load')),
    passed       BOOLEAN     NOT NULL,
    metric_value NUMERIC,                  -- e.g. % change, row count
    details      TEXT,
    checked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_quality_results_run
    ON ops.quality_results (run_id);
CREATE INDEX IF NOT EXISTS ix_quality_results_source_time
    ON ops.quality_results (source, checked_at DESC);

RESET ROLE;