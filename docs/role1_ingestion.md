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
`python -m pytest` runs parser, validation and staging tests on saved samples (no internet needed).
