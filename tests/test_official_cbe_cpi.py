"""Tests for the CBE CPI workbook (tasks 5.2 and 7.6). Offline: uses a saved real sample."""

import os

import pytest

from src.connectors.official_file import (
    OfficialFileConnector,
    month_label_to_period,
    parse_cbe_cpi_workbook,
)
from src.transform.official_staging import build_official_file_staging, rows_from_file

SAMPLE = os.path.join(
    os.path.dirname(__file__), "samples", "cbe_cpi_monthly_2025_2026.xlsx"
)


def test_month_labels():
    assert month_label_to_period("  Sept. 2025") == (2025, 9)
    assert month_label_to_period(" Aug.2007") == (2007, 8)
    assert month_label_to_period("Relative Weights") is None
    assert month_label_to_period(100) is None


def test_parse_real_sample():
    rows = parse_cbe_cpi_workbook(SAMPLE)
    assert rows[0] == ("2025-07", 252.9)
    assert dict(rows)["2026-03"] == 283.9
    assert len(rows) == 10  # May and June 2026 were not published yet: skipped


def test_connector_parse_and_validate():
    c = OfficialFileConnector(url="http://example.test/x.xls")
    valid, rejected = c.validate(c.parse({"file_path": SAMPLE}))
    assert len(valid) == 10 and not rejected
    assert valid[0]["indicator_code"] == "CPI_URBAN_INDEX"
    assert valid[0]["country"] == "EGY" and valid[0]["source"] == "official_file"


def test_fails_loudly_on_wrong_file(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["not", "a", "cpi", "file"])
    path = tmp_path / "other.xlsx"
    wb.save(path)
    with pytest.raises(ValueError):
        parse_cbe_cpi_workbook(str(path))


def test_staging_adds_yoy_only_when_base_month_exists():
    def rec(period, value):
        return {
            "source": "official_file",
            "indicator_code": "CPI_URBAN_INDEX",
            "country": "EGY",
            "period": period,
            "value": value,
        }

    out = build_official_file_staging(
        [rec("2025-03", 200.0), rec("2026-03", 250.0), rec("2026-04", 260.0)]
    )
    yoy = [r for r in out if r["indicator_code"] == "CPI_URBAN_YOY"]
    assert len(yoy) == 1 and yoy[0]["period_year"] == 2026 and yoy[0]["value"] == 25.0
    assert len([r for r in out if r["indicator_code"] == "CPI_URBAN_INDEX"]) == 3


def test_fetch_falls_back_to_local_file(tmp_path):
    class Blocked:
        def get(self, *a, **k):
            class R:
                status_code = 403
                content = b"<html>Request Rejected</html>"

                def raise_for_status(self):
                    raise RuntimeError("403")

            return R()

    c = OfficialFileConnector(
        url="http://example.test/x.xls", save_dir=str(tmp_path), session=Blocked()
    )
    c.LOCAL_PATH = SAMPLE
    raw = c.fetch()
    assert raw["file_name"] == os.path.basename(SAMPLE) and raw["size_bytes"] > 1000
    valid, _ = rows_from_file(raw["file_path"])
    assert valid


def test_fetch_without_fallback_explains_what_to_do(tmp_path):
    class Blocked:
        def get(self, *a, **k):
            raise RuntimeError("403")

    c = OfficialFileConnector(
        url="http://example.test/x.xls", save_dir=str(tmp_path), session=Blocked()
    )
    c.LOCAL_PATH = None
    with pytest.raises(RuntimeError, match="OFFICIAL_FILE_PATH"):
        c.fetch()


def test_staging_skips_invalid_periods_and_missing_values():
    def rec(period, value):
        return {
            "source": "official_file",
            "indicator_code": "CPI_URBAN_INDEX",
            "country": "EGY",
            "period": period,
            "value": value,
        }

    out = build_official_file_staging(
        [
            rec("2025", 200.0),  # Annual: not accepted
            rec("invalid", 210.0),  # Invalid period
            rec("2026-03", None),  # Missing value
            rec("2026-04", 260.0),  # Valid monthly record
        ]
    )

    assert len(out) == 1
    assert out[0]["period_year"] == 2026
    assert out[0]["period_month"] == 4
    assert out[0]["value"] == 260.0


def test_staging_skips_yoy_when_previous_value_is_zero():
    def rec(period, value):
        return {
            "source": "official_file",
            "indicator_code": "CPI_URBAN_INDEX",
            "country": "EGY",
            "period": period,
            "value": value,
        }

    out = build_official_file_staging(
        [
            rec("2025-03", 0.0),
            rec("2026-03", 250.0),
        ]
    )

    assert len(out) == 2
    assert all(r["indicator_code"] == "CPI_URBAN_INDEX" for r in out)
