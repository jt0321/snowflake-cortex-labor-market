-- ============================================================
-- AI & the Labor Market — Snowflake Cortex AI Project
-- 00_setup.sql — Environment bootstrap
-- ============================================================

USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS LABOR_MARKET;
CREATE SCHEMA  IF NOT EXISTS LABOR_MARKET.RAW;
-- ANALYTICS is unused — dbt (see dbt/profiles.yml) targets CORTEX for both
-- the staging views and mart tables, so all transformed data lives there.
CREATE SCHEMA  IF NOT EXISTS LABOR_MARKET.ANALYTICS;
CREATE SCHEMA  IF NOT EXISTS LABOR_MARKET.CORTEX;

CREATE WAREHOUSE IF NOT EXISTS LABOR_WH
  WAREHOUSE_SIZE = 'X-SMALL'
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE;

USE DATABASE  LABOR_MARKET;
USE SCHEMA    RAW;
USE WAREHOUSE LABOR_WH;

-- Internal stage for news headline JSON files
CREATE STAGE IF NOT EXISTS NEWS_STAGE
  FILE_FORMAT = (TYPE = 'JSON' STRIP_OUTER_ARRAY = TRUE);

-- Internal stage for BLS / FRED CSV files
CREATE STAGE IF NOT EXISTS ECON_STAGE
  FILE_FORMAT = (TYPE = 'CSV' SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');
