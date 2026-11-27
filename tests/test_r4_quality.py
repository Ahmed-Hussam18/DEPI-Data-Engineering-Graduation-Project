"""Unit tests for R4 quality checks and ops_log (tasks 2.12, 4.13, 5.4-5.8)."""

import pytest

from src.common import ops_log
from src.quality import checks


class FakeCursor:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.responses.pop(0) if self.responses else (0,)


class FakeConn:
    def __init__(self, responses=None):
        self.cur = FakeCursor(responses)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_pre_load_checks_all_pass_and_log_to_ops(monkeypatch):
    logged = []
    monkeypatch.setattr(
        ops_log,
        "log_quality",
        lambda *args: logged.append(args),
    )
    # row_count=10, nulls=0, duplicates=0, price_range=0
    cur = FakeCursor(responses=[(10,), (0,), (0,), (0,)])
    results = checks.run_pre_load_checks(cur, 1, "fx_gold", "staging.fx_gold_clean")

    assert [r["check_name"] for r in results] == [
        "row_count",
        "nulls",
        "duplicates",
        "price_range",
    ]
    assert all(r["passed"] for r in results)
    assert len(logged) == 4
    assert all(entry[3] == "critical" and entry[4] == "pre_load" for entry in logged)


def test_pre_load_checks_detect_nulls_duplicates_and_bad_price(monkeypatch):
    logged = []
    monkeypatch.setattr(ops_log, "log_quality", lambda *args: logged.append(args))
    # row_count=5, nulls=2, duplicates=1, price_range=3
    cur = FakeCursor(responses=[(5,), (2,), (1,), (3,)])
    results = checks.run_pre_load_checks(cur, 9, "static_site", "staging.prices_clean")

    by_name = {r["check_name"]: r for r in results}
    assert by_name["row_count"]["passed"] is True
    assert by_name["nulls"]["passed"] is False
    assert by_name["duplicates"]["passed"] is False
    assert by_name["price_range"]["passed"] is False
    assert len(logged) == 4


def test_pre_load_checks_rejects_unknown_table():
    with pytest.raises(ValueError, match="Unsupported staging table"):
        checks.run_pre_load_checks(FakeCursor(), 1, "x", "staging.unknown")


def test_post_load_checks_warn_on_drop_stale_and_jump(monkeypatch):
    logged = []
    monkeypatch.setattr(ops_log, "log_quality", lambda *args: logged.append(args))
    # recent_rows=50, prev_count=100 (50% drop -> warn), age_days=5 (>3 -> warn), jumps=1, max_pct=65.0
    cur = FakeCursor(responses=[(50,), (100,), (5,), (1, 65.0)])
    results = checks.run_post_load_checks(cur, 2, "fx_gold", "dwh.fact_gold_fx")

    by_name = {r["check_name"]: r for r in results}
    assert by_name["row_count"]["passed"] is False
    assert by_name["freshness"]["passed"] is False
    assert by_name["price_jump"]["passed"] is False
    assert all(entry[3] == "warning" and entry[4] == "post_load" for entry in logged)


def test_post_load_checks_pass_for_indicators(monkeypatch):
    logged = []
    monkeypatch.setattr(ops_log, "log_quality", lambda *args: logged.append(args))
    # recent_rows=66, prev_count=None, age_days=330 (<=730)
    cur = FakeCursor(responses=[(66,), (None,), (330,)])
    results = checks.run_post_load_checks(cur, 3, "world_bank", "dwh.fact_indicator")

    assert [r["check_name"] for r in results] == ["row_count", "freshness"]
    assert all(r["passed"] for r in results)
    assert len(logged) == 2


def test_ops_log_start_and_finish_run(monkeypatch):
    conn = FakeConn(responses=[(42,)])
    monkeypatch.setattr(ops_log, "_connect", lambda: conn)

    run_id = ops_log.start_run("fx_gold_daily", "fx_gold")
    assert run_id == 42
    assert conn.committed and conn.closed

    conn2 = FakeConn()
    monkeypatch.setattr(ops_log, "_connect", lambda: conn2)
    ops_log.finish_run(42, "failed", error_message="boom")
    sql, params = conn2.cur.queries[0]
    assert "UPDATE ops.pipeline_runs" in sql
    assert params == ("failed", None, "boom", 42)


def test_pre_load_checks_indicators_rules(monkeypatch):
    logged = []
    monkeypatch.setattr(ops_log, "log_quality", lambda *args: logged.append(args))
    # row_count=428, nulls=0, duplicates=0, price_range=1 (e.g. CPI_URBAN_INDEX <= 0)
    cur = FakeCursor(responses=[(428,), (0,), (0,), (1,)])
    results = checks.run_pre_load_checks(
        cur, 7, "official_file", "staging.indicators_clean"
    )
    by_name = {r["check_name"]: r for r in results}
    assert by_name["nulls"]["passed"] is True
    assert by_name["price_range"]["passed"] is False


def test_ops_log_rejected_rows_and_quality(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(ops_log, "_connect", lambda: conn)
    count = ops_log.log_rejected_rows(
        "fx_gold",
        "validate",
        [{"reason": "missing egp", "record": {"usd": {}}}],
        run_id=5,
    )
    assert count == 1
    assert "INSERT INTO ops.records_rejected" in conn.cur.queries[0][0]

    conn2 = FakeConn()
    monkeypatch.setattr(ops_log, "_connect", lambda: conn2)
    ops_log.log_quality(5, "fx_gold", "nulls", "critical", "pre_load", True, 0.0, "ok")
    assert "INSERT INTO ops.quality_results" in conn2.cur.queries[0][0]