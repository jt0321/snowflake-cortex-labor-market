-- Cortex AI transformation layer for labor market news classification and analysis
-- Co-authored with CoCo
-- ============================================================
-- 02_cortex_transforms.sql — Cortex AI transformation layer
-- Run after raw tables are populated.
-- ============================================================
USE ROLE SYSADMIN;
USE SCHEMA LABOR_MARKET.CORTEX;

-- ----------------------------------------------------------
-- Step 1: Classify headlines
-- Categories: layoff | hiring | ai_fear | ai_positive | policy | neutral
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE NEWS_CLASSIFIED AS
SELECT
  article_id,
  source_name,
  published_at,
  full_text,
  AI_CLASSIFY(
    full_text,
    ['layoff', 'hiring', 'ai_fear', 'ai_positive', 'policy', 'neutral']
  ):labels[0]::VARCHAR AS category,
  AI_FILTER(
    PROMPT('The article mentions artificial intelligence, automation, or machine learning as a contributing factor to job losses, layoffs, or unemployment: {0}', full_text)
  ) AS ai_causal_flag
FROM LABOR_MARKET.RAW.RAW_NEWS_HEADLINES
WHERE published_at >= '2022-01-01';

-- ----------------------------------------------------------
-- Step 2: Embed headlines for semantic search
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE NEWS_EMBEDDINGS AS
SELECT
  article_id,
  full_text,
  published_at,
  category,
  AI_EMBED('snowflake-arctic-embed-m-v1.5', full_text) AS embedding
FROM NEWS_CLASSIFIED;

-- ----------------------------------------------------------
-- Step 3: Monthly theme rollup using AI_AGG
-- No context-window limit — handles all headlines in a month
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE MONTHLY_SENTIMENT_THEMES AS
SELECT
  DATE_TRUNC('month', published_at)::DATE AS month,
  AI_AGG(
    full_text,
    'Identify the 3-5 dominant themes in these news headlines about jobs, employment, and AI. For each theme, note whether it suggests AI is causing displacement, creating opportunity, or is unrelated to employment outcomes. Be concise.'
  ) AS theme_summary,
  COUNT(*)                        AS headline_count,
  SUM(ai_causal_flag::INT)        AS ai_causal_count
FROM NEWS_CLASSIFIED
GROUP BY 1
ORDER BY 1;

-- ----------------------------------------------------------
-- Step 4: Monthly narrative digest using AI_COMPLETE
-- Joins economic data + theme summary for each month
-- ----------------------------------------------------------
CREATE OR REPLACE TABLE MONTHLY_DIGEST AS
WITH econ AS (
  SELECT
    DATE_TRUNC('month', observation_date)::DATE AS month,
    MAX(CASE WHEN series_id = 'UNRATE'  THEN value END) AS unemployment_rate,
    MAX(CASE WHEN series_id = 'PAYEMS'  THEN value END) AS nonfarm_payroll_k
  FROM LABOR_MARKET.RAW.RAW_FRED_SERIES
  GROUP BY 1
),
layoffs AS (
  SELECT
    DATE_FROM_PARTS(year, REPLACE(period, 'M', '')::INT, 1) AS month,
    SUM(value) AS total_layoffs_k
  FROM LABOR_MARKET.RAW.RAW_BLS_JOLTS
  WHERE series_id LIKE '%LAY%'
  GROUP BY 1
),
joined AS (
  SELECT
    e.month,
    e.unemployment_rate,
    e.nonfarm_payroll_k,
    l.total_layoffs_k,
    t.theme_summary,
    t.headline_count,
    t.ai_causal_count
  FROM econ e
  LEFT JOIN layoffs         l ON e.month = l.month
  LEFT JOIN MONTHLY_SENTIMENT_THEMES t ON e.month = t.month
)
SELECT
  month,
  unemployment_rate,
  nonfarm_payroll_k,
  total_layoffs_k,
  headline_count,
  ai_causal_count,
  AI_COMPLETE(
    'mistral-7b',
    CONCAT(
      'Write a 3-sentence economic digest for ', month::VARCHAR, '. ',
      'Unemployment rate: ', COALESCE(unemployment_rate::VARCHAR, 'N/A'), '%. ',
      'Nonfarm payrolls: ', COALESCE(nonfarm_payroll_k::VARCHAR, 'N/A'), 'K. ',
      'Total layoffs: ', COALESCE(total_layoffs_k::VARCHAR, 'N/A'), 'K. ',
      'News headlines this month (', COALESCE(headline_count::VARCHAR, '0'), ' total, ',
      COALESCE(ai_causal_count::VARCHAR, '0'), ' citing AI as a cause): ',
      COALESCE(theme_summary, 'No headlines captured this month.'), ' ',
      'Assess whether the data supports or contradicts the fear that AI is driving displacement.'
    )
  ) AS narrative_digest
FROM joined
ORDER BY month;

-- ----------------------------------------------------------
-- Step 5: Cortex Search service for semantic headline search
-- ----------------------------------------------------------
CREATE OR REPLACE CORTEX SEARCH SERVICE HEADLINE_SEARCH
  ON full_text
  ATTRIBUTES category, published_at, source_name, ai_causal_flag
  WAREHOUSE = LABOR_WH
  TARGET_LAG = '1 day'
  AS (
    SELECT full_text, category, published_at, source_name, ai_causal_flag, article_id
    FROM NEWS_CLASSIFIED
  );
