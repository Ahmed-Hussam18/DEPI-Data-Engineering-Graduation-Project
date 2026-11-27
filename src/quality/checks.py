"""Data quality checks for staging (pre-load critical) and dwh (post-load warning).

Tasks 4.13, 5.4, 5.5, 5.6, 5.7 (owner: R4).
All results are written to ops.quality_results exclusively via src/common/ops_log.py.
"""

from src.common import ops_log

# Table-driven rules for pre-load critical checks (quality_gate).
PRE_LOAD_RULES = {
    "staging.prices_clean": {
        "nulls_where": (
            "product_id IS NULL OR btrim(product_id) = '' "
            "OR price_date IS NULL OR price IS NULL"
        ),
        "dup_cols": "product_id, source, price_date",
        "range_where": "price <= 0",
        "range_desc": "price <= 0",
    },
    "staging.fx_gold_clean": {
        "nulls_where": (
            "code IS NULL OR btrim(code) = '' "
            "OR kind IS NULL OR rate_date IS NULL OR rate IS NULL"
        ),
        "dup_cols": "source, code, kind, COALESCE(karat, 0), rate_date",
        "range_where": "rate <= 0",
        "range_desc": "rate <= 0",
    },
    "staging.indicators_clean": {
        # World Bank keeps missing years with value=NULL (task 4.10), and annual rows have period_month=NULL.
        "nulls_where": (
            "indicator_code IS NULL OR btrim(indicator_code) = '' "
            "OR country IS NULL OR btrim(country) = '' OR period_year IS NULL"
        ),
        "dup_cols": "source, indicator_code, country, period_year, COALESCE(period_month, 0)",
        "range_where": (
            "(indicator_code = 'CPI_URBAN_INDEX' AND (value IS NULL OR value <= 0)) "
            "OR (indicator_code <> 'CPI_URBAN_INDEX' AND value IS NOT NULL AND value < -100)"
        ),
        "range_desc": "out-of-range indicator value",
    },
}

# Expected max data age (in days) per source for post-load freshness check.
FRESHNESS_DAYS = {
    "static_site": 2,
    "fx_gold": 3,
    "official_file": 365,
    "world_bank": 730,
}

# Daily fact tables that support day-over-day price_jump (> 50%) check.
DAILY_JUMP_CONFIG = {
    "dwh.fact_price": ("product_key", "price"),
    "dwh.fact_gold_fx": ("currency_key", "rate"),
}


def _scalar(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def run_pre_load_checks(cur, run_id: int, source: str, staging_table: str) -> list[dict]:
    """Run critical staging checks and log every result to ops.quality_results.

    Checks: row_count (> 0), nulls, duplicates, price_range.
    Returns a list of dicts: [{"check_name", "passed", "metric_value", "details"}, ...].
    """
    if staging_table not in PRE_LOAD_RULES:
        raise ValueError(f"Unsupported staging table for quality checks: {staging_table}")

    rules = PRE_LOAD_RULES[staging_table]
    results = []

    row_count = _scalar(
        cur, f"SELECT count(*) FROM {staging_table} WHERE source = %s", (source,)
    ) or 0
    results.append({
        "check_name": "row_count",
        "passed": row_count > 0,
        "metric_value": float(row_count),
        "details": f"{row_count} rows in {staging_table}",
    })

    null_bad = _scalar(
        cur,
        f"SELECT count(*) FROM {staging_table} "
        f"WHERE source = %s AND ({rules['nulls_where']})",
        (source,),
    ) or 0
    results.append({
        "check_name": "nulls",
        "passed": null_bad == 0,
        "metric_value": float(null_bad),
        "details": f"{null_bad} rows with missing required fields in {staging_table}",
    })

    dup_groups = _scalar(
        cur,
        f"SELECT count(*) FROM ("
        f"SELECT 1 FROM {staging_table} WHERE source = %s "
        f"GROUP BY {rules['dup_cols']} HAVING count(*) > 1"
        f") AS dups",
        (source,),
    ) or 0
    results.append({
        "check_name": "duplicates",
        "passed": dup_groups == 0,
        "metric_value": float(dup_groups),
        "details": f"{dup_groups} duplicate key group(s) in {staging_table}",
    })

    range_bad = _scalar(
        cur,
        f"SELECT count(*) FROM {staging_table} "
        f"WHERE source = %s AND ({rules['range_where']})",
        (source,),
    ) or 0
    results.append({
        "check_name": "price_range",
        "passed": range_bad == 0,
        "metric_value": float(range_bad),
        "details": f"{range_bad} rows failing range ({rules['range_desc']}) in {staging_table}",
    })

    for item in results:
        ops_log.log_quality(
            run_id,
            source,
            item["check_name"],
            "critical",
            "pre_load",
            item["passed"],
            item["metric_value"],
            item["details"],
        )
    return results


def _check_row_count_drop(cur, run_id: int, source: str, fact_table: str) -> dict:
    """Warning check: warn if current loaded/staging count dropped > 30% vs previous run."""
    recent_rows = _scalar(
        cur,
        f"SELECT count(*) FROM {fact_table} f "
        "JOIN dwh.dim_source s ON s.source_key = f.source_key "
        "WHERE s.source_name = %s AND f.loaded_at >= now() - interval '1 day'",
        (source,),
    ) or 0

    prev_count = _scalar(
        cur,
        "SELECT records_count FROM ops.pipeline_runs "
        "WHERE source = %s AND status = 'success' AND run_id < %s "
        "AND records_count IS NOT NULL "
        "ORDER BY run_id DESC LIMIT 1",
        (source, run_id),
    )

    if prev_count and prev_count > 0:
        drop_pct = ((prev_count - recent_rows) / prev_count) * 100.0
        passed = drop_pct <= 30.0
        details = (
            f"{recent_rows} rows in {fact_table} (last 24h) vs previous {prev_count} "
            f"(drop {drop_pct:.1f}%)"
        )
        metric = round(drop_pct, 2)
    else:
        passed = recent_rows > 0
        details = f"{recent_rows} rows written to {fact_table} in the last day (baseline run)"
        metric = float(recent_rows)

    return {
        "check_name": "row_count",
        "passed": passed,
        "metric_value": metric,
        "details": details,
    }


def _check_freshness(cur, source: str, fact_table: str) -> dict:
    """Warning check: verify latest observed date in DWH is within expected age."""
    max_age_days = FRESHNESS_DAYS.get(source, 7)
    if fact_table == "dwh.fact_indicator":
        age_days = _scalar(
            cur,
            "SELECT (CURRENT_DATE - MAX(make_date(f.period_year, GREATEST(f.period_month, 1), 1)))::int "
            "FROM dwh.fact_indicator f "
            "JOIN dwh.dim_source s ON s.source_key = f.source_key "
            "WHERE s.source_name = %s",
            (source,),
        )
    else:
        age_days = _scalar(
            cur,
            f"SELECT (CURRENT_DATE - MAX(d.full_date))::int "
            f"FROM {fact_table} f "
            "JOIN dwh.dim_source s ON s.source_key = f.source_key "
            "JOIN dwh.dim_date d ON d.date_key = f.date_key "
            "WHERE s.source_name = %s",
            (source,),
        )

    if age_days is None:
        return {
            "check_name": "freshness",
            "passed": False,
            "metric_value": None,
            "details": f"no rows found in {fact_table} for {source}",
        }

    passed = age_days <= max_age_days
    return {
        "check_name": "freshness",
        "passed": passed,
        "metric_value": float(age_days),
        "details": f"latest data age is {age_days} day(s) (threshold <= {max_age_days})",
    }


def _check_price_jump(cur, source: str, fact_table: str) -> dict | None:
    """Warning check: warn if any daily series changed > 50% vs its previous day."""
    cfg = DAILY_JUMP_CONFIG.get(fact_table)
    if cfg is None:
        return None
    entity_col, value_col = cfg
    cur.execute(
        f"WITH ordered AS ("
        f"  SELECT f.{entity_col} AS entity_id, d.full_date, f.{value_col} AS val, "
        f"         LAG(f.{value_col}) OVER (PARTITION BY f.{entity_col} ORDER BY d.full_date) AS prev_val "
        f"  FROM {fact_table} f "
        f"  JOIN dwh.dim_source s ON s.source_key = f.source_key "
        f"  JOIN dwh.dim_date d ON d.date_key = f.date_key "
        f"  WHERE s.source_name = %s"
        f"), latest AS ("
        f"  SELECT max(full_date) AS max_d FROM ordered"
        f") "
        f"SELECT count(*) FILTER (WHERE prev_val > 0 AND abs(val - prev_val) / prev_val > 0.5), "
        f"       coalesce(max(abs(val - prev_val) / NULLIF(prev_val, 0)) * 100.0, 0) "
        f"FROM ordered, latest "
        f"WHERE ordered.full_date = latest.max_d AND prev_val IS NOT NULL",
        (source,),
    )
    jumps, max_pct = cur.fetchone()
    jumps = jumps or 0
    max_pct = round(float(max_pct or 0.0), 2)
    return {
        "check_name": "price_jump",
        "passed": jumps == 0,
        "metric_value": max_pct,
        "details": f"{jumps} series jumped > 50% on latest day (max {max_pct:.2f}%)",
    }


def run_post_load_checks(cur, run_id: int, source: str, fact_table: str) -> list[dict]:
    """Run warning checks after load and log every result to ops.quality_results."""
    results = [
        _check_row_count_drop(cur, run_id, source, fact_table),
        _check_freshness(cur, source, fact_table),
    ]
    jump = _check_price_jump(cur, source, fact_table)
    if jump is not None:
        results.append(jump)

    for item in results:
        ops_log.log_quality(
            run_id,
            source,
            item["check_name"],
            "warning",
            "post_load",
            item["passed"],
            item["metric_value"],
            item["details"],
        )
    return results