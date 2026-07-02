from dagster import (
    AssetSelection,
    ScheduleDefinition,
    define_asset_job,
)
from dagster_project.assets.ingestion import (
    raw_stock_prices, raw_layoffs_fyi, raw_news_headlines, raw_polymarket_markets,
    raw_fred_icsa, raw_econ_monthly,
)
from dagster_project.assets.dbt_assets import (
    dbt_transforms, cortex_search_service,
)

# ── Daily (6 AM UTC) ──────────────────────────────────────────────────────
# Ingest stocks, news, layoffs → run tag:daily dbt models (+ staging ancestors) → refresh Cortex Search

daily_ingest_and_transform_job = define_asset_job(
    name="daily_ingest_and_transform",
    selection=AssetSelection.assets(
        raw_stock_prices, raw_layoffs_fyi, raw_news_headlines, raw_polymarket_markets,
    ) | AssetSelection.tag("daily", "").upstream() | AssetSelection.assets(cortex_search_service),
)

daily_schedule = ScheduleDefinition(
    name="daily_ingestion_and_transform",
    cron_schedule="0 6 * * *",
    job=daily_ingest_and_transform_job,
)

# ── Weekly (Thursday 8 AM UTC — ICSA drops every Thursday) ───────────────

weekly_icsa_job = define_asset_job(
    name="weekly_icsa_refresh",
    selection=AssetSelection.assets(raw_fred_icsa),
)

weekly_schedule = ScheduleDefinition(
    name="weekly_icsa_refresh",
    cron_schedule="0 8 * * 4",  # Thursday
    job=weekly_icsa_job,
)

# ── Monthly (2nd of month, 9 AM UTC — after BLS/FRED release window) ─────
# Full econ ingest → regenerate all monthly digest + AI_AGG models

monthly_digest_job = define_asset_job(
    name="monthly_econ_and_digest",
    selection=AssetSelection.assets(raw_econ_monthly)
              | AssetSelection.tag("monthly", "").upstream(),
)

monthly_schedule = ScheduleDefinition(
    name="monthly_econ_and_digest",
    cron_schedule="0 9 2 * *",  # 2nd of each month
    job=monthly_digest_job,
)
