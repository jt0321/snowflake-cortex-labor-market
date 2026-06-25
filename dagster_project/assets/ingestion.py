"""
Dagster assets wrapping the ingestion scripts.
Each asset writes to a Snowflake RAW table and is idempotent (scripts dedup on load).
"""
import sys
from pathlib import Path

from dagster import asset, AssetExecutionContext

# Make ingestion scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ingestion"))

import fetch_econ
import fetch_layoffs
import fetch_stocks
import fetch_news


# ── Daily ──────────────────────────────────────────────────────────────────

@asset(
    group_name="ingestion_daily",
    description="Daily closing prices for MSFT, GOOGL, AMZN, TSLA, QQQ from Yahoo Finance",
    tags={"schedule": "daily"},
)
def raw_stock_prices(context: AssetExecutionContext) -> None:
    fetch_stocks.main()
    context.log.info("raw_stock_prices ingestion complete")


@asset(
    group_name="ingestion_daily",
    description="Tech company layoffs from Layoffs.fyi (Airtable scrape) — updates continuously",
    tags={"schedule": "daily"},
)
def raw_layoffs_fyi(context: AssetExecutionContext) -> None:
    fetch_layoffs.main()
    context.log.info("raw_layoffs_fyi ingestion complete")


@asset(
    group_name="ingestion_daily",
    description="News headlines from NewsAPI matching AI, layoff, and IPO queries",
    tags={"schedule": "daily"},
)
def raw_news_headlines(context: AssetExecutionContext) -> None:
    fetch_news.main()
    context.log.info("raw_news_headlines ingestion complete")


# ── Weekly (Thursday — ICSA initial claims drop weekly) ───────────────────

@asset(
    group_name="ingestion_weekly",
    description="FRED weekly ICSA initial claims refresh (releases every Thursday)",
    tags={"schedule": "weekly"},
)
def raw_fred_icsa(context: AssetExecutionContext) -> None:
    import snowflake.connector
    from dagster_project.resources import SNOWFLAKE_CONFIG
    conn = snowflake.connector.connect(**SNOWFLAKE_CONFIG)
    df = fetch_econ.fetch_fred("ICSA")
    n = fetch_econ.load_to_snowflake(df, "RAW_FRED_SERIES", conn)
    conn.close()
    context.log.info(f"ICSA: loaded {n} rows")


# ── Monthly (BLS publishes ~3 weeks after month-end) ─────────────────────

@asset(
    group_name="ingestion_monthly",
    description="Full BLS JOLTS + CPS + FRED (UNRATE, PAYEMS) monthly refresh",
    tags={"schedule": "monthly"},
)
def raw_econ_monthly(context: AssetExecutionContext) -> None:
    fetch_econ.main()
    context.log.info("raw_econ_monthly ingestion complete")
