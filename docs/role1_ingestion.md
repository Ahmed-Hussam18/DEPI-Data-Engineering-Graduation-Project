# Role 1: APIs and official file (documentation)

## What it does
Three connectors collect data and save it untouched in `raw`; staging builders then clean it.

| Source | File | Raw table | Staging table |
|---|---|---|---|
| FX / gold | `src/connectors/fx_gold.py` | `raw.api_responses` | `staging.fx_gold_clean` |
| World Bank | `src/connectors/world_bank.py` | `raw.api_responses` | `staging.indicators_clean` |
| Official file (CBE CPI) | `src/connectors/official_file.py` | `raw.files` (+ file on the volume) | `staging.indicators_clean` via `src/transform/official_staging.py` |

## Flow of one run
`fetch()` (timeout, status check, JSON shape check) -> `raw_store` (save raw) -> `parse()` -> `validate()` (valid rows + rejected rows with a reason) -> staging builder.

## How Role 4 plugs it into a DAG
```python
from src.connectors.fx_gold import FxGoldConnector
from src.transform.api_staging import load_fx_gold_staging

valid, rejected = FxGoldConnector().run(store=True)   # fetch + save raw + parse + validate
# log `rejected` to ops.records_rejected with stage='validate' (ops_log.py)
load_fx_gold_staging()                                 # rebuild staging from raw
```
Same pattern for `WorldBankConnector` and `load_indicator_staging()`.

Official file (weekly or monthly; the CBE publishes monthly, so monthly is enough):
```python
from src.connectors.official_file import OfficialFileConnector
from src.transform.official_staging import load_official_file_staging

valid, rejected = OfficialFileConnector().run(store=True)   # download + raw.files + parse + validate
load_official_file_staging()                                 # rebuild staging from the latest file
```
Set `OFFICIAL_FILE_PATH` to a manually downloaded copy if the CBE site refuses the download (see `docs/sources.md` section 3). The Airflow image needs `xlrd` (added to `docker/airflow/requirements.txt`) to read the `.xls`.
Schedules: FX/gold daily; World Bank and the official file weekly or monthly.

## Decisions
- Gold = international spot price converted to EGP per gram (24/21/18 karat). Not the jeweller's price.
- World Bank years without data are kept with `value = NULL`. Nothing is filled or invented.
- If the same day is collected twice, the latest collection wins in staging.
- `raw` is never deleted, so staging can always be rebuilt.

## Limits (be honest in the demo)
- Dollar/gold history starts on 2024-03-02 (the first date the API has).
- Correlation with the price index uses ~30 days only and is **not causation**.
- The official file lags the CBE web page by a few months, and two old fiscal years have gaps (see `docs/sources.md`).
- Source: fawazahmed0 currency API, the World Bank open data and the Central Bank of Egypt (CPI, built by CAPMAS).

## Tests
`python -m pytest` runs parser, validation, staging and fetch tests on saved samples (no internet, no database needed). The database code (`raw_store`, the `load_*` staging functions) is tested with small fakes that record the SQL.

| Test file | What it checks |
|---|---|
| `tests/test_fx_gold.py` | gold and currency math, validation rules |
| `tests/test_world_bank.py` | parsing, NULL years kept, validation |
| `tests/test_api_staging.py` | staging builders: latest collection wins, gaps kept as NULL |
| `tests/test_official_file.py` | flat CSV mode, Arabic header normalisation, fails loudly when columns change |
| `tests/test_official_cbe_cpi.py` | CBE workbook parsing on a real sample, year-over-year staging, download fallback |
| `tests/test_r1_pipeline.py` | fallback URL, "all endpoints failed", World Bank API errors, `run()`, `raw_store` and staging loaders delete only their own source |

## Run it yourself (collect and stage)
Needs Python 3.12+ with `python -m pip install -r requirements-dev.txt psycopg2-binary`, and a Postgres database `eco` created from `sql/*.sql` (docker compose does this on first start). Connection: `ECO_DB_URL` (for example `postgresql://etl_user:PASSWORD@localhost:5432/eco`) or the `POSTGRES_*` / `ETL_USER_PASSWORD` variables, see `src/common/raw_store.py`.
```bash
python scripts/backfill_fx_gold.py 2024-03-02 2026-11-26   # FX / gold history (about 20 min, safe to repeat)
python -c "from src.connectors.world_bank import WorldBankConnector as W; W().run(store=True)"
python -c "from src.connectors.official_file import OfficialFileConnector as O; O().run(store=True)"
python -c "from src.transform.api_staging import load_fx_gold_staging, load_indicator_staging; load_fx_gold_staging(); load_indicator_staging()"
python -c "from src.transform.official_staging import load_official_file_staging; load_official_file_staging()"
```
Result checked on 2026-11-26: 6993 rows in `staging.fx_gold_clean` (2024-03-02 to 2026-11-26), 66 World Bank rows (1960 to 2025), 428 official-file rows (230 CPI index values plus 198 year-over-year values).

## Known data gaps
- FX / gold: the API has no data for **2025-12-10** (both the jsDelivr and the pages.dev link answer 404). The backfill reports it as one failed day. 2026-08-19 exists only on the pages.dev fallback link, which the connector uses automatically. All other days from 2024-03-02 to 2026-11-26 were checked.
- Official file: see `docs/sources.md` section 3 (lag behind the web page, two fiscal years with missing months).
- World Bank: some years have no value and are kept as NULL on purpose.

## Troubleshooting
| Message | Meaning and fix |
|---|---|
| `FX/Gold: all endpoints failed` | The API has no file for that day, or no internet. A single failed day is normal (see gaps). |
| `World Bank ... Read timed out` | The server is slow. Run the command again. |
| `Official file download failed ... set OFFICIAL_FILE_PATH` | The CBE firewall refused the script. Download the `.xls` in a browser and set `OFFICIAL_FILE_PATH` to it. |
| `Official file: no 'All Items' CPI row ...` | CBE changed the file layout. Look at the file and update `parse_cbe_cpi_workbook()`. |
| `password authentication failed` | `ECO_DB_URL` or `ETL_USER_PASSWORD` does not match the password used when the database was created. |
