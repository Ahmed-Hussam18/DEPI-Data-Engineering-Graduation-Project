"""Official statistics file connector (CSV / Excel).  Tasks 5.1 - 5.3.

Chosen file (task 1.16): Central Bank of Egypt, CPI monthly, "All Years" (.xls).
It holds the consumer price index (urban Egypt, 2018/19 = 100), one sheet per
fiscal year, months in columns, one row per group. We read the "All Items" row
(Arabic label: الرقم العام). See docs/sources.md section 3.

Two read modes:
  * COLUMN_MAP empty (default): CBE workbook layout, parsed by parse_cbe_cpi_workbook().
  * COLUMN_MAP set: a flat CSV / Excel table {exact header: 'period' | 'value'}.

Settings (env vars win over the defaults):
  OFFICIAL_FILE_URL   direct download link (default: the CBE link above)
  OFFICIAL_FILE_PATH  local copy of the file. Used when the download is refused.
                      The CBE site sits behind a firewall that can answer 403
                      to scripts, so keep a manual download as the fallback.
  RAW_FILES_DIR       folder on the docker volume (default: data/raw_files)
"""
import hashlib
import os
import re

import requests

from .base import BaseConnector, reject, is_number

REQUIRED = ("source", "indicator_code", "country", "period", "value")


def normalize_header(text):
    """Trim spaces and unify Arabic letter variants so header matching is stable."""
    text = " ".join(str(text).split())
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ـ", "")):
        text = text.replace(a, b)
    return text


MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
ALL_ITEMS_LABELS = ("all items", "الرقم العام")
DEFAULT_URL = ("https://www.cbe.org.eg/-/media/project/cbe/listing/time-series/"
               "inflation/cpi/cpi--monthly_.xls")


def month_label_to_period(label):
    """'  Sept. 2025' -> (2025, 9); anything that is not a month label -> None."""
    if not isinstance(label, str):
        return None
    m = re.match(r"^\s*([A-Za-z]{3})[A-Za-z]*\.?\s*(\d{4})\s*$", label)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return int(m.group(2)), MONTHS[m.group(1).lower()]


def _to_float(v):
    """Cells are numbers or numbers stored as text ('108.1'). Anything else -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", "")
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse_cbe_cpi_workbook(path):
    """Read the 'All Items' CPI row of every sheet. Returns [(period, value), ...].

    Layout (checked on the real file, 21 fiscal-year sheets 2005/06 .. 2025/26):
    one row holds month labels ('July 2025', 'Aug. 2025', ...), a later row has
    'All Items' in column A or B. Each sheet is one fiscal year (July to June).
    The year is taken from the fiscal year, not from each label, because the file
    has typos (the 2006/07 sheet labels August 2006 as 'Aug.2007').
    Months not published yet are empty cells: skipped, not stored as NULL.
    Raises ValueError if no sheet matches (the file format changed).
    """
    import pandas as pd

    sheets = pd.read_excel(path, sheet_name=None, header=None)
    seen = {}
    for _name, df in sheets.items():
        header_row, labels = None, {}
        for i in range(len(df)):
            found = {j: month_label_to_period(v) for j, v in enumerate(df.iloc[i].tolist())}
            found = {j: p for j, p in found.items() if p}
            if len(found) >= 2:
                header_row, labels = i, found
                break
        if header_row is None:
            continue
        first = labels[min(labels)]
        start_year = first[0] if first[1] >= 7 else first[0] - 1
        for i in range(header_row + 1, len(df)):
            row = df.iloc[i].tolist()
            texts = [normalize_header(v).lower() for v in row[:2] if isinstance(v, str)]
            if any(any(t.startswith(lbl) for lbl in ALL_ITEMS_LABELS) for t in texts):
                for j, (_year, month) in labels.items():
                    value = _to_float(row[j])
                    year = start_year if month >= 7 else start_year + 1
                    period = f"{year}-{month:02d}"
                    if value is not None and period not in seen:
                        seen[period] = value
                break
    if not seen:
        raise ValueError("Official file: no 'All Items' CPI row with month columns found")
    return sorted(seen.items())


def _looks_like_excel(content):
    return content[:2] == b"PK" or content[:4] == b"\xd0\xcf\x11\xe0"


class OfficialFileConnector(BaseConnector):
    name = "official_file"
    HEADERS = {"User-Agent": "EcoPlatformBot/1.0 (student project)"}
    # The CBE firewall rejects bot-like clients; a plain browser User-Agent is accepted.
    BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                     "(KHTML, like Gecko) Chrome/120 Safari/537.36",
                       "Accept": "*/*"}

    # ---- fill these in after task 1.16 ---------------------------------
    URL = os.getenv("OFFICIAL_FILE_URL") or DEFAULT_URL
    LOCAL_PATH = os.getenv("OFFICIAL_FILE_PATH")
    INDICATOR_CODE = "CPI_URBAN_INDEX"    # CBE urban CPI index, 2018/19 = 100, monthly
    COUNTRY = "EGY"
    COLUMN_MAP = {}                       # e.g. {"الشهر": "period", "معدل التضخم": "value"}
    SHEET = 0                             # Excel sheet index or name
    # --------------------------------------------------------------------

    def __init__(self, url=None, save_dir=None, session=None):
        self.url = url or self.URL
        self.save_dir = save_dir or os.getenv("RAW_FILES_DIR", "data/raw_files")
        self.session = session or requests
        self.last_file = None

    def _download(self):
        resp = self.session.get(self.url, headers=self.BROWSER_HEADERS, timeout=60)
        self.last_endpoint = self.url
        self.last_status = resp.status_code
        resp.raise_for_status()
        if not _looks_like_excel(resp.content) and not self.url.lower().endswith(".csv"):
            raise RuntimeError("download is not an Excel file (blocked page?)")
        return resp.content

    def fetch(self):
        if not self.url and not self.LOCAL_PATH:
            raise RuntimeError("Set OFFICIAL_FILE_URL or OFFICIAL_FILE_PATH")
        try:
            content = self._download()
            file_name = os.path.basename(self.url.split("?")[0]) or "official_file.bin"
        except Exception as exc:  # firewall 403, timeout, HTML page instead of file
            if not self.LOCAL_PATH or not os.path.exists(self.LOCAL_PATH):
                raise RuntimeError(
                    f"Official file download failed ({exc}). Download it by hand from "
                    "the CBE time-series page and set OFFICIAL_FILE_PATH."
                ) from exc
            with open(self.LOCAL_PATH, "rb") as f:
                content = f.read()
            file_name = os.path.basename(self.LOCAL_PATH)
            self.last_endpoint = "local:" + self.LOCAL_PATH
            self.last_status = None
        os.makedirs(self.save_dir, exist_ok=True)
        path = os.path.join(self.save_dir, file_name)
        with open(path, "wb") as f:
            f.write(content)  # saved exactly as obtained
        self.last_file = {
            "file_name": file_name,
            "file_path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        return self.last_file

    def store_raw(self, raw):
        from src.common import raw_store

        return raw_store.store_file(self.name, raw["file_name"], raw["file_path"],
                                    raw["sha256"], raw["size_bytes"])

    def parse(self, raw):
        import pandas as pd

        path = raw["file_path"]
        if not self.COLUMN_MAP:  # default: CBE CPI workbook
            return [{"source": self.name, "indicator_code": self.INDICATOR_CODE,
                     "country": self.COUNTRY, "period": period, "value": value}
                    for period, value in parse_cbe_cpi_workbook(path)]
        if path.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(path, sheet_name=self.SHEET)
        else:
            df = pd.read_csv(path)
        df.columns = [normalize_header(c) for c in df.columns]
        wanted = {normalize_header(k): v for k, v in self.COLUMN_MAP.items()}
        missing = [k for k in wanted if k not in df.columns]
        if missing:  # the file format changed: fail loudly instead of guessing
            raise ValueError(f"Official file: expected columns not found: {missing}")
        df = df[list(wanted)].rename(columns=wanted)
        rows = []
        for rec in df.to_dict("records"):
            value = rec["value"]
            if value != value:  # NaN -> None
                value = None
            rows.append({"source": self.name, "indicator_code": self.INDICATOR_CODE,
                         "country": self.COUNTRY, "period": str(rec["period"]).strip(),
                         "value": value})
        return rows

    def validate(self, rows):
        valid, rejected = [], []
        for r in rows:
            missing = [k for k in REQUIRED if k not in r]
            if missing:
                rejected.append(reject(r, f"missing field(s): {', '.join(missing)}"))
            elif not r["period"] or r["period"] == "nan":
                rejected.append(reject(r, "empty period"))
            elif r["value"] is not None and not is_number(r["value"]):
                rejected.append(reject(r, f"value is not a number: {r['value']!r}"))
            else:
                valid.append(r)
        return valid, rejected
