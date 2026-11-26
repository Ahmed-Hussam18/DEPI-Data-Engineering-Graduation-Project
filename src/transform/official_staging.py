"""Staging builder for the official file (tasks 5.1 - 5.2, feeds 4.9 style staging).

raw.files (CBE CPI workbook)  --(parse + validate)-->  staging.indicators_clean

Two series are written for source 'official_file':
  CPI_URBAN_INDEX  the monthly CPI index (2018/19 = 100), as published
  CPI_URBAN_YOY    year-over-year change in %, computed here from the index:
                   (index / index 12 months earlier - 1) * 100
A month without a value 12 months earlier gets no YOY row (nothing is invented).

Like api_staging.py: build_* is a pure function (unit tested), load_* talks to
Postgres and rebuilds this source's rows on every run (idempotent).
"""
from src.connectors.official_file import OfficialFileConnector
from src.transform.api_staging import split_period

INDEX_NAME = "Consumer price index, urban Egypt (2018/19 = 100)"
YOY_NAME = "Urban CPI, year-over-year change (computed from the index)"


def build_official_file_staging(rows):
    """rows: validated records from OfficialFileConnector. Returns staging rows."""
    index = {}
    for r in rows:
        parts = split_period(r["period"])
        if parts is None or parts[1] is None or r["value"] is None:
            continue
        index[parts] = (r, r["value"])
    out = []
    for (year, month), (r, value) in sorted(index.items()):
        base = {"source": r["source"], "country": r["country"], "frequency": "monthly",
                "period_year": year, "period_month": month}
        out.append({**base, "indicator_code": r["indicator_code"],
                    "indicator_name": INDEX_NAME, "unit": "index", "value": value})
        prev = index.get((year - 1, month))
        if prev and prev[1]:
            out.append({**base, "indicator_code": "CPI_URBAN_YOY",
                        "indicator_name": YOY_NAME, "unit": "%",
                        "value": round((value / prev[1] - 1) * 100, 4)})
    return out


def rows_from_file(file_path):
    """Parse + validate one saved file. Returns (valid_rows, rejected_rows)."""
    c = OfficialFileConnector(url="file")
    return c.validate(c.parse({"file_path": file_path}))


# ----------------------------------------------------------- database part
def load_official_file_staging():
    """Rebuild this source's rows in staging.indicators_clean from the LATEST
    file in raw.files. Returns the number of rows written."""
    from psycopg2.extras import execute_values
    from src.common.raw_store import _connect

    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_path FROM raw.files WHERE source = 'official_file' "
                    "ORDER BY collected_at DESC LIMIT 1")
                found = cur.fetchone()
                if not found:
                    return 0
                valid, _rejected = rows_from_file(found[0])
                rows = build_official_file_staging(valid)
                cur.execute("DELETE FROM staging.indicators_clean "
                            "WHERE source = 'official_file'")
                if rows:
                    execute_values(
                        cur,
                        "INSERT INTO staging.indicators_clean "
                        "(source, indicator_code, indicator_name, unit, frequency, country, "
                        "period_year, period_month, value) VALUES %s",
                        [(r["source"], r["indicator_code"], r["indicator_name"], r["unit"],
                          r["frequency"], r["country"], r["period_year"], r["period_month"],
                          r["value"]) for r in rows])
                return len(rows)
    finally:
        conn.close()
