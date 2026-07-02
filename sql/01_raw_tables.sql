-- ============================================================
-- 01_raw_tables.sql — Raw layer DDL
-- ============================================================
USE ROLE SYSADMIN;
USE SCHEMA LABOR_MARKET.RAW;

-- BLS JOLTS — monthly layoffs, openings, quits by industry
CREATE TABLE IF NOT EXISTS RAW_BLS_JOLTS (
  series_id       VARCHAR,    -- e.g. JTS000000000000000LAY (total layoffs)
  year            NUMBER,
  period          VARCHAR,    -- M01-M12
  period_name     VARCHAR,
  value           FLOAT,      -- thousands of persons
  footnotes       VARCHAR,
  industry_code   VARCHAR,
  industry_name   VARCHAR,
  loaded_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- BLS CPS — unemployment + labor force participation
CREATE TABLE IF NOT EXISTS RAW_BLS_CPS (
  series_id       VARCHAR,
  year            NUMBER,
  period          VARCHAR,
  period_name     VARCHAR,
  value           FLOAT,
  loaded_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- FRED series — UNRATE, PAYEMS, ICSA (initial claims)
CREATE TABLE IF NOT EXISTS RAW_FRED_SERIES (
  series_id        VARCHAR,   -- e.g. UNRATE
  observation_date DATE,
  value            FLOAT,
  loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- News headlines
CREATE TABLE IF NOT EXISTS RAW_NEWS_HEADLINES (
  article_id      VARCHAR,    -- MD5 of URL
  source_name     VARCHAR,
  author          VARCHAR,
  title           VARCHAR,
  description     VARCHAR,
  url             VARCHAR,
  published_at    TIMESTAMP_NTZ,
  full_text       VARCHAR,    -- title + description for Cortex input
  loaded_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Tech layoffs from Layoffs.fyi
CREATE TABLE IF NOT EXISTS RAW_LAYOFFS_FYI (
  layoff_id        VARCHAR,   -- unique hash to prevent duplicates
  company          VARCHAR,
  location_hq      VARCHAR,
  industry         VARCHAR,
  laid_off_count   NUMBER,
  percentage       FLOAT,
  laid_off_date    DATE,
  stage            VARCHAR,
  funds_raised_m   FLOAT,
  country          VARCHAR,
  source_url       VARCHAR,
  loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Stock prices (MSFT, GOOGL, AMZN, TSLA, QQQ)
CREATE TABLE IF NOT EXISTS RAW_STOCK_PRICES (
  ticker            VARCHAR,
  observation_date  DATE,
  close_val         FLOAT,
  loaded_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Polymarket prediction-market probabilities (recession, unemployment, AI jobs, IPOs)
CREATE TABLE IF NOT EXISTS RAW_POLYMARKET_MARKETS (
  market_id        VARCHAR,
  question         VARCHAR,
  outcome          VARCHAR,    -- e.g. 'Yes' / 'No'
  probability      FLOAT,      -- implied probability, 0-1
  volume           FLOAT,
  liquidity        FLOAT,
  end_date         DATE,
  snapshot_date    DATE,       -- date this probability was captured
  loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

