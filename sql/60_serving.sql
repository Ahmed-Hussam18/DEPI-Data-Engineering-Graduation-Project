-- 60_serving.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- serving layer: VIEWS ONLY. FastAPI and Grafana read from here with the
-- `reader` role (SELECT on serving only, see 10_schemas.sql).
-- Views run with their owner's rights (etl_user), so they can read dwh/ops
-- while reader has no direct access to those schemas.
--
-- Column names are the contract with R5: do not rename without telling R5.
-- The tables are empty until data is loaded (sample data: task 2.10), so
-- these views return no rows yet, but their columns are final.

SET ROLE etl_user;

-- GET /prices/latest : latest price of every product per source
CREATE OR REPLACE VIEW serving.v_latest_prices AS
SELECT DISTINCT ON (p.product_id, s.source_name)
       p.product_id,
       p.name        AS product_name,
       p.category,
       p.unit,
       s.source_name AS source,
       d.full_date   AS price_date,
       f.price,
       f.unit_price
FROM dwh.fact_price f
JOIN dwh.dim_product p ON p.product_key = f.product_key
JOIN dwh.dim_source  s ON s.source_key  = f.source_key
JOIN dwh.dim_date    d ON d.date_key    = f.date_key
ORDER BY p.product_id, s.source_name, d.full_date DESC;

-- GET /products/{id}/history : price history with day-over-day change
CREATE OR REPLACE VIEW serving.v_product_history AS
SELECT p.product_id,
       p.name        AS product_name,
       p.category,
       s.source_name AS source,
       d.full_date   AS price_date,
       f.price,
       f.unit_price,
       f.price / NULLIF(LAG(f.price) OVER (
           PARTITION BY p.product_id, s.source_name
           ORDER BY d.full_date), 0) - 1 AS pct_change
FROM dwh.fact_price f
JOIN dwh.dim_product p ON p.product_key = f.product_key
JOIN dwh.dim_source  s ON s.source_key  = f.source_key
JOIN dwh.dim_date    d ON d.date_key    = f.date_key;

-- GET /index : basket price index (base = 100 at each product's first day).
-- INTERIM version: equal weights. Final weights + fill-forward come in
-- tasks 6.1 / 6.2.
CREATE OR REPLACE VIEW serving.v_basket_index AS
WITH prices AS (
    SELECT p.product_id, d.full_date, f.price
    FROM dwh.fact_price f
    JOIN dwh.dim_product p ON p.product_key = f.product_key
    JOIN dwh.dim_date    d ON d.date_key    = f.date_key
),
base AS (
    SELECT DISTINCT ON (product_id) product_id, price AS base_price
    FROM prices
    ORDER BY product_id, full_date
)
SELECT pr.full_date AS index_date,
       ROUND(100 * AVG(pr.price / b.base_price), 2) AS index_value,
       COUNT(*)                                     AS products_count
FROM prices pr
JOIN base b ON b.product_id = pr.product_id
GROUP BY pr.full_date;

-- GET /pipeline/status : last run of every source
CREATE OR REPLACE VIEW serving.v_pipeline_status AS
SELECT DISTINCT ON (source)
       source,
       dag_id,
       run_date,
       status,
       started_at,
       finished_at,
       records_count,
       error_message
FROM ops.pipeline_runs
ORDER BY source, started_at DESC, run_id DESC;

-- Pipeline-health dashboard: rejected records grouped by cause
CREATE OR REPLACE VIEW serving.v_rejected_summary AS
SELECT source,
       stage,
       reason,
       COUNT(*)           AS rejected_count,
       MAX(rejected_at)   AS last_rejected_at
FROM ops.records_rejected
GROUP BY source, stage, reason;

-- Pipeline-health dashboard: latest result of every quality check
CREATE OR REPLACE VIEW serving.v_quality_summary AS
SELECT DISTINCT ON (source, check_name)
       source,
       check_name,
       severity,
       phase,
       passed,
       metric_value,
       details,
       checked_at
FROM ops.quality_results
ORDER BY source, check_name, checked_at DESC, id DESC;

RESET ROLE;