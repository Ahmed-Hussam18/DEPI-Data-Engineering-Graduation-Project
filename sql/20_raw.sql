-- 20_raw.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- raw layer: source data exactly as collected + source + collection time.
-- Lets us re-process after a cleaning bug without collecting again
-- (prices cannot be collected retroactively).
-- Written ONLY through src/common/raw_store.py (code rule 3).

SET ROLE etl_user;

-- JSON responses from APIs (FX/Gold, World Bank)
CREATE TABLE IF NOT EXISTS raw.api_responses (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT         NOT NULL,   -- e.g. 'fx_gold', 'world_bank'
    endpoint      TEXT,                    -- URL or endpoint called
    http_status   INTEGER,
    payload       JSONB        NOT NULL,   -- response body, untouched
    collected_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_api_responses_source_time
    ON raw.api_responses (source, collected_at);

-- HTML pages from the static shopping site
CREATE TABLE IF NOT EXISTS raw.html_pages (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT         NOT NULL,   -- e.g. 'static_site'
    url           TEXT         NOT NULL,
    http_status   INTEGER,
    html          TEXT         NOT NULL,   -- page source, untouched
    collected_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_html_pages_source_time
    ON raw.html_pages (source, collected_at);

-- Official files (CSV/Excel). The file itself lives on a docker volume;
-- this table is its registry.
CREATE TABLE IF NOT EXISTS raw.files (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT         NOT NULL,   -- e.g. 'official_file'
    file_name     TEXT         NOT NULL,
    file_path     TEXT         NOT NULL,   -- path on the volume
    sha256        TEXT,                    -- detect re-downloads of same file
    size_bytes    BIGINT,
    collected_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_files_source_time
    ON raw.files (source, collected_at);

RESET ROLE;