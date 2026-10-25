-- 40_dwh.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- Star schema + SCD Type 2. Names follow checklist section 6.
-- Load order is mandatory: dimensions first, then facts (section 10).

SET ROLE etl_user;

-- ---------------------------------------------------------------- dimensions

-- Calendar. date_key = YYYYMMDD. Pre-filled, safe to re-run.
CREATE TABLE IF NOT EXISTS dwh.dim_date (
    date_key      INTEGER  PRIMARY KEY,
    full_date     DATE     NOT NULL UNIQUE,
    day_of_month  SMALLINT NOT NULL,
    day_of_week   SMALLINT NOT NULL,      -- 1 = Monday ... 7 = Sunday
    week_of_year  SMALLINT NOT NULL,
    month         SMALLINT NOT NULL,
    month_name    TEXT     NOT NULL,
    quarter       SMALLINT NOT NULL,
    year          SMALLINT NOT NULL
);

INSERT INTO dwh.dim_date
SELECT to_char(d, 'YYYYMMDD')::int,
       d::date,
       EXTRACT(day     FROM d),
       EXTRACT(isodow  FROM d),
       EXTRACT(week    FROM d),
       EXTRACT(month   FROM d),
       trim(to_char(d, 'Month')),
       EXTRACT(quarter FROM d),
       EXTRACT(year    FROM d)
FROM generate_series('2020-01-01'::date, '2035-12-31'::date, interval '1 day') AS d
ON CONFLICT (date_key) DO NOTHING;

-- Data sources. source_name must equal the `source` value the connectors emit.
CREATE TABLE IF NOT EXISTS dwh.dim_source (
    source_key   SERIAL PRIMARY KEY,
    source_name  TEXT NOT NULL UNIQUE,
    source_type  TEXT NOT NULL CHECK (source_type IN ('api', 'website', 'file'))
);

INSERT INTO dwh.dim_source (source_name, source_type) VALUES
    ('fx_gold',       'api'),
    ('world_bank',    'api'),
    ('static_site',   'website'),
    ('official_file', 'file')
ON CONFLICT (source_name) DO NOTHING;

-- Products, SCD Type 2. product_id is the STABLE id (SKU / URL slug),
-- product_key is the surrogate key of each version.
CREATE TABLE IF NOT EXISTS dwh.dim_product (
    product_key  SERIAL  PRIMARY KEY,
    product_id   TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    category     TEXT,
    unit         TEXT,
    valid_from   DATE    NOT NULL,
    valid_to     DATE,                    -- NULL while current
    is_current   BOOLEAN NOT NULL DEFAULT TRUE
);
-- At most ONE current version per product.
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_product_current
    ON dwh.dim_product (product_id) WHERE is_current;
CREATE INDEX IF NOT EXISTS ix_dim_product_id
    ON dwh.dim_product (product_id);

-- Currencies and gold karats.
CREATE TABLE IF NOT EXISTS dwh.dim_currency (
    currency_key  SERIAL PRIMARY KEY,
    code          TEXT NOT NULL,          -- USD, EUR, XAU ...
    kind          TEXT NOT NULL CHECK (kind IN ('currency', 'gold')),
    karat         SMALLINT                -- 24 / 21 / 18, NULL for currencies
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_currency
    ON dwh.dim_currency (code, kind, COALESCE(karat, 0));

-- Economic indicators.
CREATE TABLE IF NOT EXISTS dwh.dim_indicator (
    indicator_key   SERIAL PRIMARY KEY,
    indicator_code  TEXT NOT NULL UNIQUE,
    indicator_name  TEXT,
    unit            TEXT,
    frequency       TEXT                  -- annual / monthly
);

-- --------------------------------------------------------------------- facts

-- One price per product / source / day. The PK is what makes UPSERT work.
CREATE TABLE IF NOT EXISTS dwh.fact_price (
    product_key  INTEGER NOT NULL REFERENCES dwh.dim_product (product_key),
    source_key   INTEGER NOT NULL REFERENCES dwh.dim_source  (source_key),
    date_key     INTEGER NOT NULL REFERENCES dwh.dim_date    (date_key),
    price        NUMERIC(12,2) NOT NULL,
    unit_price   NUMERIC(12,4),
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_key, source_key, date_key)
);
CREATE INDEX IF NOT EXISTS ix_fact_price_date    ON dwh.fact_price (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_price_product ON dwh.fact_price (product_key);

-- One rate per currency-or-gold / source / day.
CREATE TABLE IF NOT EXISTS dwh.fact_gold_fx (
    currency_key  INTEGER NOT NULL REFERENCES dwh.dim_currency (currency_key),
    source_key    INTEGER NOT NULL REFERENCES dwh.dim_source   (source_key),
    date_key      INTEGER NOT NULL REFERENCES dwh.dim_date     (date_key),
    rate          NUMERIC(18,6) NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (currency_key, source_key, date_key)
);
CREATE INDEX IF NOT EXISTS ix_fact_gold_fx_date ON dwh.fact_gold_fx (date_key);

-- Indicators are yearly/monthly, so they use period_year/period_month
-- instead of a daily date_key. period_month = 0 means annual data.
CREATE TABLE IF NOT EXISTS dwh.fact_indicator (
    indicator_key  INTEGER NOT NULL REFERENCES dwh.dim_indicator (indicator_key),
    source_key     INTEGER NOT NULL REFERENCES dwh.dim_source    (source_key),
    country        TEXT    NOT NULL,
    period_year    SMALLINT NOT NULL,
    period_month   SMALLINT NOT NULL DEFAULT 0 CHECK (period_month BETWEEN 0 AND 12),
    value          NUMERIC(18,6),         -- NULL allowed: World Bank has gaps
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (indicator_key, source_key, country, period_year, period_month)
);

RESET ROLE;