-- 30_staging.sql
-- Owner: R3 (Warehouse & SQL Lead)
-- staging layer: cleaned + unified data BEFORE it enters the warehouse.
-- Column names match what the dwh load SQL (checklist section 10) expects:
-- products(product_id, name, category, unit)
-- prices_clean(product_id, source, price, price_date)
--
-- Rebuilt on every run by the transform step (R2 / R1).
-- Deliberately NO UNIQUE / NOT NULL constraints on checked columns:
-- the quality_gate (R4) must be the one that detects NULLs, duplicates
-- and bad prices, and fails the task before load.

SET ROLE etl_user;

-- Products (one row per product, name already normalized)
CREATE TABLE IF NOT EXISTS staging.products (
    product_id    TEXT,          -- stable SKU / URL slug (never from the name)
    name          TEXT,          -- normalized Arabic name
    category      TEXT,
    unit          TEXT           -- kg / g / l ...
);

-- Cleaned daily prices
CREATE TABLE IF NOT EXISTS staging.prices_clean (
    product_id    TEXT,
    source        TEXT,
    price         NUMERIC(12,2),
    unit_price    NUMERIC(12,4), -- price per base unit (kg / l)
    currency      TEXT,
    price_date    DATE,          -- Africa/Cairo date
    observed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_prices_clean_key
    ON staging.prices_clean (product_id, source, price_date);

-- Cleaned FX / gold rates
CREATE TABLE IF NOT EXISTS staging.fx_gold_clean (
    source        TEXT,
    code          TEXT,          -- USD, EUR, XAU ...
    kind          TEXT,          -- 'currency' | 'gold'
    karat         INTEGER,       -- 24 / 21 / 18, NULL for currencies
    rate          NUMERIC(18,6),
    rate_date     DATE,          -- Africa/Cairo date
    observed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_fx_gold_clean_key
    ON staging.fx_gold_clean (code, karat, rate_date);

-- Cleaned economic indicators (World Bank + official file)
CREATE TABLE IF NOT EXISTS staging.indicators_clean (
    source          TEXT,
    indicator_code  TEXT,
    indicator_name  TEXT,
    unit            TEXT,
    frequency       TEXT,        -- annual / monthly
    country         TEXT,
    period_year     INTEGER,
    period_month    INTEGER,     -- NULL for annual data
    value           NUMERIC(18,6)
);
CREATE INDEX IF NOT EXISTS ix_indicators_clean_key
    ON staging.indicators_clean (indicator_code, country, period_year, period_month);

RESET ROLE;