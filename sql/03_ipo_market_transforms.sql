-- IPO market transform layer with AI classification, filtering, and digest generation
-- Co-authored with CoCo
-- ============================================================
-- 03_ipo_market_transforms.sql — Ingestion transform layer
-- Run after RAW_LAYOFFS_FYI and RAW_STOCK_PRICES are loaded.
-- ============================================================
USE ROLE SYSADMIN;
USE SCHEMA LABOR_MARKET.CORTEX;

-- ----------------------------------------------------------
-- Step 1: Clean and structure Layoffs.fyi data
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE LAYOFFS_FYI_CLEAN AS
SELECT
  layoff_id,
  company,
  location_hq,
  industry,
  COALESCE(laid_off_count, 0) AS laid_off_count,
  COALESCE(percentage, 0.0) AS percentage,
  laid_off_date,
  stage,
  COALESCE(funds_raised_m, 0.0) AS funds_raised_m,
  country,
  source_url
FROM LABOR_MARKET.RAW.RAW_LAYOFFS_FYI
WHERE laid_off_date >= '2022-01-01';

-- ----------------------------------------------------------
-- Step 2: Compute monthly stock closing prices and returns
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE STOCK_MONTHLY_PERFORMANCE AS
WITH daily_prices AS (
  SELECT
    ticker,
    observation_date,
    close_val,
    ROW_NUMBER() OVER (PARTITION BY ticker, DATE_TRUNC('month', observation_date) ORDER BY observation_date DESC) as rn_desc,
    ROW_NUMBER() OVER (PARTITION BY ticker, DATE_TRUNC('month', observation_date) ORDER BY observation_date ASC) as rn_asc
  FROM LABOR_MARKET.RAW.RAW_STOCK_PRICES
),
month_ends AS (
  SELECT
    ticker,
    DATE_TRUNC('month', observation_date)::DATE AS month,
    close_val AS end_close
  FROM daily_prices
  WHERE rn_desc = 1
),
month_starts AS (
  SELECT
    ticker,
    DATE_TRUNC('month', observation_date)::DATE AS month,
    close_val AS start_close
  FROM daily_prices
  WHERE rn_asc = 1
)
SELECT
  me.ticker,
  me.month,
  me.end_close AS close_val,
  ms.start_close,
  ((me.end_close - ms.start_close) / ms.start_close) * 100 AS monthly_return_pct
FROM month_ends me
JOIN month_starts ms ON me.ticker = ms.ticker AND me.month = ms.month
ORDER BY me.month, me.ticker;

-- ----------------------------------------------------------
-- Step 3: Classify OpenAI, Anthropic, SpaceX, and general IPO news
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE NEWS_IPO_CLASSIFIED AS
SELECT
  article_id,
  source_name,
  published_at,
  full_text,
  CASE 
    WHEN LOWER(full_text) LIKE '%openai%' THEN 'OpenAI'
    WHEN LOWER(full_text) LIKE '%anthropic%' THEN 'Anthropic'
    WHEN LOWER(full_text) LIKE '%spacex%' THEN 'SpaceX'
    ELSE 'Tech Sector'
  END AS target_company,
  AI_CLASSIFY(
    full_text,
    ['ipo_optimism', 'ipo_pessimism', 'valuation_hype', 'layoff_fear', 'neutral']
  ):labels[0]::VARCHAR AS category,
  AI_FILTER(
    PROMPT('The article mentions valuations, private funding rounds, investments, or discussions about an IPO or secondary sale: {0}', full_text)
  ) AS ipo_flag
FROM LABOR_MARKET.RAW.RAW_NEWS_HEADLINES
WHERE published_at >= '2020-01-01'
  AND (
    LOWER(full_text) LIKE '%openai%' 
    OR LOWER(full_text) LIKE '%anthropic%' 
    OR LOWER(full_text) LIKE '%spacex%' 
    OR LOWER(full_text) LIKE '%ipo%'
  );

-- ----------------------------------------------------------
-- Step 4: Aggregate monthly IPO sentiment themes via AI_AGG
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE MONTHLY_IPO_SENTIMENT AS
SELECT
  DATE_TRUNC('month', published_at)::DATE AS month,
  AI_AGG(
    full_text,
    'Summarize the monthly sentiment, valuation rumors, and IPO discussion trends regarding OpenAI, Anthropic, and SpaceX. Highlight key themes like optimism, pessimism, private funding rounds, or valuation changes. Be extremely concise.'
  ) AS ipo_theme_summary,
  COUNT(*) AS ipo_headline_count,
  SUM(ipo_flag::INT) AS ipo_flag_count
FROM NEWS_IPO_CLASSIFIED
GROUP BY 1
ORDER BY 1;

-- ----------------------------------------------------------
-- Step 5: Generate integrated monthly macroeconomic + market digest
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE MONTHLY_INTEGRATED_DIGEST AS
WITH econ AS (
  SELECT
    DATE_TRUNC('month', observation_date)::DATE AS month,
    MAX(CASE WHEN series_id = 'UNRATE'  THEN value END) AS unemployment_rate,
    MAX(CASE WHEN series_id = 'PAYEMS'  THEN value END) AS nonfarm_payroll_k
  FROM LABOR_MARKET.RAW.RAW_FRED_SERIES
  GROUP BY 1
),
bls_layoffs AS (
  SELECT
    DATE_FROM_PARTS(year, REPLACE(period, 'M', '')::INT, 1) AS month,
    SUM(value) AS bls_total_layoffs_k
  FROM LABOR_MARKET.RAW.RAW_BLS_JOLTS
  WHERE series_id LIKE '%LAY%'
  GROUP BY 1
),
fyi_layoffs AS (
  SELECT
    DATE_TRUNC('month', laid_off_date)::DATE AS month,
    SUM(laid_off_count) AS fyi_tech_layoffs
  FROM LAYOFFS_FYI_CLEAN
  GROUP BY 1
),
stocks AS (
  SELECT
    month,
    MAX(CASE WHEN ticker = 'QQQ'   THEN close_val END) AS qqq_close,
    MAX(CASE WHEN ticker = 'QQQ'   THEN monthly_return_pct END) AS qqq_return,
    MAX(CASE WHEN ticker = 'MSFT'  THEN close_val END) AS msft_close,
    MAX(CASE WHEN ticker = 'MSFT'  THEN monthly_return_pct END) AS msft_return,
    MAX(CASE WHEN ticker = 'GOOGL' THEN close_val END) AS googl_close,
    MAX(CASE WHEN ticker = 'GOOGL' THEN monthly_return_pct END) AS googl_return
  FROM STOCK_MONTHLY_PERFORMANCE
  GROUP BY 1
),
news AS (
  SELECT
    month,
    ipo_theme_summary,
    ipo_headline_count,
    ipo_flag_count
  FROM MONTHLY_IPO_SENTIMENT
)
SELECT
  e.month,
  e.unemployment_rate,
  e.nonfarm_payroll_k,
  COALESCE(l.bls_total_layoffs_k, 0) AS bls_total_layoffs_k,
  COALESCE(f.fyi_tech_layoffs, 0) AS fyi_tech_layoffs,
  s.qqq_close,
  s.qqq_return,
  s.msft_close,
  s.msft_return,
  s.googl_close,
  s.googl_return,
  n.ipo_theme_summary,
  COALESCE(n.ipo_headline_count, 0) AS ipo_headline_count,
  COALESCE(n.ipo_flag_count, 0) AS ipo_flag_count,
  AI_COMPLETE(
    'mistral-7b',
    CONCAT(
      'Write a 3-sentence economic and market digest for ', e.month::VARCHAR, '. ',
      'Broader economy: Unemployment is ', COALESCE(e.unemployment_rate::VARCHAR, 'N/A'), '%, Nonfarm payrolls: ', COALESCE(e.nonfarm_payroll_k::VARCHAR, 'N/A'), 'K, Total layoffs (BLS): ', COALESCE(l.bls_total_layoffs_k::VARCHAR, 'N/A'), 'K. ',
      'Tech Sector Layoffs (layoffs.fyi): ', COALESCE(f.fyi_tech_layoffs::VARCHAR, '0'), '. ',
      'Market performance: QQQ return is ', COALESCE(ROUND(s.qqq_return, 1)::VARCHAR, 'N/A'), '%, MSFT (OpenAI proxy) return is ', COALESCE(ROUND(s.msft_return, 1)::VARCHAR, 'N/A'), '%. ',
      'IPO headlines (', COALESCE(n.ipo_headline_count::VARCHAR, '0'), ' total): ', COALESCE(n.ipo_theme_summary, 'No news on Anthropic, OpenAI, or SpaceX IPOs.'), ' ',
      'Synthesize how tech stock trends and private company valuation/IPO news relate to labor layoffs in this month.'
    )
  ) AS ipo_market_digest
FROM econ e
LEFT JOIN bls_layoffs l ON e.month = l.month
LEFT JOIN fyi_layoffs f ON e.month = f.month
LEFT JOIN stocks      s ON e.month = s.month
LEFT JOIN news        n ON e.month = n.month
ORDER BY e.month;
