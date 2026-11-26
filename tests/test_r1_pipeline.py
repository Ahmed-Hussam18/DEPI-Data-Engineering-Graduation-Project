"""Extra R1 tests (task 7.6): fetch fallbacks, API errors, run(), raw_store and the
staging loaders. Offline: network and database are replaced by small fakes."""

import json
import os

import pytest
import requests

from src.connectors.fx_gold import FxGoldConnector
from src.connectors.world_bank import WorldBankConnector

HERE = os.path.dirname(__file__)


def sample(name):
    with open(os.path.join(HERE, "samples", name), encoding="utf-8") as f:
        return json.load(f)


class FakeResponse:
    def __init__(self, data=None, status=200):
        self._data, self.status_code = data, status
        self.content = b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeSession:
    """Returns the queued responses one by one and remembers the URLs asked."""

    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


# ---------------------------------------------------------------- FX / gold fetch
def test_fx_fetch_uses_fallback_when_first_url_fails():
    good = sample("fx_gold_usd_latest.json")
    session = FakeSession(FakeResponse(status=404), FakeResponse(good))
    c = FxGoldConnector(date="2026-08-19", session=session)
    assert c.fetch() == good
    assert "jsdelivr" in session.urls[0] and "pages.dev" in session.urls[1]
    assert c.last_endpoint == session.urls[1] and c.last_status == 200


def test_fx_fetch_raises_when_every_endpoint_fails():
    # 2025-12-10 is such a day: both URLs answer 404 (see docs/sources.md)
    session = FakeSession(FakeResponse(status=404), FakeResponse(status=404))
    with pytest.raises(RuntimeError, match="all endpoints failed"):
        FxGoldConnector(date="2025-12-10", session=session).fetch()


def test_fx_fetch_rejects_bad_json_shape():
    bad = {"date": "2026-10-25", "usd": {"eur": 0.9}}  # no egp
    session = FakeSession(FakeResponse(bad), FakeResponse(bad))
    with pytest.raises(RuntimeError):
        FxGoldConnector(session=session).fetch()


def test_fx_rejects_zero_and_missing_rates():
    raw = {"date": "2026-10-25", "usd": {"egp": 50.0, "eur": 0.5, "xau": 0}}
    c = FxGoldConnector()
    valid, rejected = c.validate(c.parse(raw))
    assert {r["code"] for r in valid} == {"USD", "EUR"}
    assert len(rejected) == 5  # GBP, SAR (not in response) and 3 gold karats (xau = 0)
    assert all("rate" in r["reason"] for r in rejected)


# ------------------------------------------------------------------ World Bank fetch
def test_world_bank_fetch_returns_data_and_keeps_null_years():
    raw = sample("world_bank_egy_inflation.json")
    c = WorldBankConnector(session=FakeSession(FakeResponse(raw)))
    data = c.fetch()
    valid, rejected = c.validate(c.parse(data))
    assert not rejected and len(valid) == len(raw[1])
    assert c.last_status == 200 and "EGY" in c.last_endpoint


def test_world_bank_api_error_message_is_raised():
    err = [{"message": [{"id": "120", "value": "Invalid format"}]}]
    c = WorldBankConnector(session=FakeSession(FakeResponse(err)))
    with pytest.raises(ValueError, match="API error"):
        c.fetch()


def test_world_bank_more_than_one_page_is_refused():
    paged = [{"page": 1, "pages": 2}, []]
    c = WorldBankConnector(session=FakeSession(FakeResponse(paged)))
    with pytest.raises(ValueError, match="more than one page"):
        c.fetch()


def test_world_bank_http_error_is_raised():
    c = WorldBankConnector(session=FakeSession(FakeResponse(status=503)))
    with pytest.raises(requests.HTTPError):
        c.fetch()


def test_world_bank_validate_rejects_bad_period_and_value():
    c = WorldBankConnector()
    rows = [
        {
            "source": "world_bank",
            "indicator_code": "X",
            "country": "EGY",
            "period": "20x3",
            "value": 1.0,
        },
        {
            "source": "world_bank",
            "indicator_code": "X",
            "country": "EGY",
            "period": "2023",
            "value": "abc",
        },
        {
            "source": "world_bank",
            "indicator_code": "X",
            "country": "EGY",
            "period": "2023",
            "value": None,
        },
    ]
    valid, rejected = c.validate(rows)
    assert len(valid) == 1 and len(rejected) == 2


# --------------------------------------------------------------- BaseConnector.run
def test_run_saves_raw_only_when_asked():
    good = sample("fx_gold_usd_latest.json")
    saved = []

    class Spy(FxGoldConnector):
        def store_raw(self, raw):
            saved.append(raw)

    c = Spy(session=FakeSession(FakeResponse(good), FakeResponse(good)))
    valid, rejected = c.run(store=True)
    assert len(saved) == 1 and valid and not rejected
    c.run(store=False)
    assert len(saved) == 1


# ------------------------------------------------------------- database fakes
class FakeCursor:
    def __init__(self, log, fetch_rows=None):
        self.log, self.fetch_rows = log, fetch_rows or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (42,)

    def fetchall(self):
        return self.fetch_rows

    # psycopg2.extras.execute_values uses these two
    def mogrify(self, template, args=None):
        return b"(" + b",".join(b"x" for _ in (args or [])) + b")"

    connection = None


class FakeConn:
    def __init__(self, fetch_rows=None):
        self.log, self.closed, self.fetch_rows = [], False, fetch_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.log, self.fetch_rows)

    def close(self):
        self.closed = True


def test_raw_store_writes_one_row_and_closes_connection(monkeypatch):
    pytest.importorskip("psycopg2")
    from src.common import raw_store

    conn = FakeConn()
    monkeypatch.setattr(raw_store, "_connect", lambda: conn)
    new_id = raw_store.store_api_response("fx_gold", "http://x", 200, {"a": 1})
    assert new_id == 42 and conn.closed
    sql, params = conn.log[0]
    assert sql.startswith("INSERT INTO raw.api_responses") and params[0] == "fx_gold"
    raw_store.store_file("official_file", "a.xls", "/tmp/a.xls", "abc", 10)
    assert "raw.files" in conn.log[-1][0]


def test_official_staging_loader_returns_zero_without_a_file(monkeypatch):
    pytest.importorskip("psycopg2")
    from src.common import raw_store
    from src.transform import official_staging

    conn = FakeConn(fetch_rows=[])

    class NoFileCursor(FakeCursor):
        def fetchone(self):
            return None

    conn.cursor = lambda: NoFileCursor(conn.log)
    monkeypatch.setattr(raw_store, "_connect", lambda: conn)
    assert official_staging.load_official_file_staging() == 0
    assert not any("DELETE" in sql for sql, _ in conn.log)  # nothing is wiped


def test_fx_staging_loader_deletes_only_its_own_source(monkeypatch):
    pytest.importorskip("psycopg2")
    from datetime import datetime

    from src.common import raw_store
    from src.transform import api_staging

    raw = sample("fx_gold_usd_latest.json")
    conn = FakeConn(fetch_rows=[(raw, datetime(2026, 10, 25, 8, 0))])
    monkeypatch.setattr(raw_store, "_connect", lambda: conn)
    monkeypatch.setattr(
        "psycopg2.extras.execute_values",
        lambda cur, sql, rows: conn.log.append(("INSERT_MANY " + sql[:40], len(rows))),
    )
    written = api_staging.load_fx_gold_staging()
    deletes = [s for s, _ in conn.log if s.startswith("DELETE")]
    assert written == 7 and deletes == [
        "DELETE FROM staging.fx_gold_clean WHERE source = 'fx_gold'"
    ]
